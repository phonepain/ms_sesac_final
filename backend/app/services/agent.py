# backend/app/services/agent.py
import time
import uuid
import structlog
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import StateGraph, END

from app.config import settings
from app.models.api import AnalysisResponse, ManuscriptInput
from app.models.enums import SourceType
from app.models.vertices import Source
from app.services.detection import DetectionService
from app.services.extraction import ExtractionService
from app.services.graph import InMemoryGraphService
from app.services.normalization import NormalizationService

# 프로젝트 내 데이터 모델 임포트
from app.models.api import DocumentChunk, ContradictionReport
from app.models.intermediate import ExtractionResult, NormalizationResult
from app.models.vertices import Source
from app.models.enums import SourceType

logger = structlog.get_logger(__name__)

# ==========================================
# 1. LangGraph 상태(State) 정의
# ==========================================
class AgentState(TypedDict):
    """LangGraph의 각 노드를 통과하며 유지/업데이트될 데이터 상태입니다."""
    text: str
    source_type: str
    source_id: str
    chunks: List[DocumentChunk]
    extractions: List[ExtractionResult]
    normalized_data: Optional[NormalizationResult]
    contradictions: List[ContradictionReport]


# ── LangGraph 상태 정의 ──────────────────────────────────────

class AgentState(TypedDict):
    manuscript: ManuscriptInput
    raw_extraction: Any
    normalized: Any
    snapshot: Any           # InMemoryGraphService 스냅샷 (격리된 복제본)
    violations: Dict        # find_all_violations() 결과
    result: Optional[AnalysisResponse]
    error: Optional[str]


# ── 노드 함수 (각 계층) ──────────────────────────────────────

async def _extract(state: AgentState) -> AgentState:
    """계층 1: 텍스트 → RawEntity"""
    logger.info("langgraph_node", node="extract")
    svc = ExtractionService()
    raw = await svc.extract_from_chunk(
        text=state["manuscript"].content,
        source_type="scenario",
        chunk_id="agent-chunk-001",
    )
    return {**state, "raw_extraction": raw}


async def _normalize(state: AgentState) -> AgentState:
    """계층 2: RawEntity → NormalizedEntity"""
    logger.info("langgraph_node", node="normalize")
    svc = NormalizationService()
    normalized = await svc.normalize(extractions=[state["raw_extraction"]])
    return {**state, "normalized": normalized}


def _snapshot(state: AgentState) -> AgentState:
    """계층 3 준비: canonical graph → In-Memory 스냅샷 복제 (canonical 보호).

    USE_LOCAL_GRAPH=True 환경에서는 빈 InMemoryGraphService를 스냅샷으로 사용.
    실제 Gremlin 연결 시: gremlin_svc.snapshot_graph() 호출.
    """
    logger.info("langgraph_node", node="snapshot")
    snapshot = InMemoryGraphService()
    return {**state, "snapshot": snapshot}


def _materialize(state: AgentState) -> AgentState:
    """계층 3: NormalizedEntity → 스냅샷에 적재 (canonical graph 불변)"""
    logger.info("langgraph_node", node="materialize")
    snapshot: InMemoryGraphService = state["snapshot"]
    normalized = state["normalized"]

    if normalized and snapshot:
        source = Source(
            source_id="snapshot",
            source_type=SourceType.MANUSCRIPT,
            name=state["manuscript"].title,
            file_path="",
        )
        snapshot.materialize(normalized, source)

    return state  # snapshot 객체 자체가 변경됨 (mutable)


def _detect(state: AgentState) -> AgentState:
    """계층 4: 스냅샷에서 7가지 모순 탐지"""
    logger.info("langgraph_node", node="detect")
    snapshot: InMemoryGraphService = state["snapshot"]
    violations = snapshot.find_all_violations()
    logger.info(
        "detect_complete",
        hard=len(violations.get("hard", [])),
        soft=len(violations.get("soft", [])),
    )
    return {**state, "violations": violations}


async def _respond(state: AgentState) -> AgentState:
    """계층 4: violations → AnalysisResponse + 스냅샷 폐기 (canonical 보호 완료)"""
    logger.info("langgraph_node", node="respond")
    svc = DetectionService()
    result = await svc.analyze(state["violations"])

    # 스냅샷 폐기: canonical graph는 한 번도 건드리지 않았음
    return {**state, "snapshot": None, "result": result}


# ── ContiCheckAgent (LangGraph 기반) ─────────────────────────

class ContiCheckAgent:
    def __init__(self):

        # 개별 서비스 초기화
        self.ingest_service = IngestService()
        self.extraction_service = ExtractionService()
        self.normalization_service = NormalizationService()
        self.detection_service = DetectionService()

        # LangGraph 워크플로우 빌드
        self.graph = self._build_graph()

    # ==========================================
    # 2. 노드(Node) 함수 정의
    # ==========================================
    async def node_ingest(self, state: AgentState) -> Dict:
        """[노드 1] 텍스트를 청크로 분할합니다."""
        logger.info("Node[Ingest]: Splitting text into chunks")
        
        # 텍스트를 바이트로 변환하여 IngestService 처리
        content_bytes = state["text"].encode("utf-8")
        chunks = await self.ingest_service.process_file(
            file_content=content_bytes, 
            filename=f"{state['source_id']}.txt", 
            source_id=state["source_id"]
        )
        # 반환된 딕셔너리가 AgentState를 업데이트함
        return {"chunks": chunks}

    async def node_extract(self, state: AgentState) -> Dict:
        """[노드 2] 청크에서 엔티티를 병렬 추출합니다."""
        logger.info("Node [Extract]: Extracting entities", chunk_count=len(state["chunks"]))
        
        extractions = await self.extraction_service.extract_from_chunks(
            chunks=state["chunks"], 
            source_type=state["source_type"]
        )
        return {"extractions": extractions}

    async def node_normalize(self, state: AgentState) -> Dict:
        """[노드 3] 추출된 데이터를 정규화/통합합니다."""
        logger.info("Node [Normalize]: Merging extracted entities")
        
        normalized = await self.normalization_service.normalize(state["extractions"])
        return {"normalized_data": normalized}

    async def node_detect(self, state: AgentState) -> Dict:
        """[노드 4] 그래프 DB 연동 및 모순 탐지 (Phase 3 + Phase 4 통합)"""
        logger.info("Node [Detect]: Materializing to DB and detecting contradictions")
        
        if not state["normalized_data"]:
            logger.warning("No normalized data to materialize.")
            return {"contradictions":[]}

        # 1. 그래프 서비스 초기화 (로컬 테스트용 InMemory)
        graph_service = get_graph_service(json_path=None)

        # 2. Source(출처) 객체 생성 (graph.py 요구사항)
        source_vertex = Source(
            id=uuid.UUID(state["source_id"].replace("src-", "").ljust(32, '0')[:32]), # UUID 포맷 맞춤
            source_type=SourceType.SCENARIO,
            name=state["filename"],
            metadata="{}"
        )

        # 3. [계층 3] 그래프 DB에 적재 (Materialization)
        graph_service.materialize(state["normalized_data"], source_vertex)
        logger.info("Materialization complete. Finding structural violations...")

        # 4. [계층 4-1] 구조적 모순 탐지 (그래프 쿼리)
        violations_dict = graph_service.find_all_violations()
        all_violations = violations_dict.get("all",[])
        logger.info("Graph queries complete", found_violations=len(all_violations))

        # 5.[계층 4-2] LLM 정밀 검증 (DetectionService)
        verified_reports =[]
        for violation in all_violations:
            logger.info("Verifying violation with LLM...", violation_type=violation.get("type"))
            # LLM 탐정에게 구조적 오류를 넘겨 검증시킴
            llm_result = await self.detection_service.verify_violation(violation)
            
            # 최종 결과 리포트에 원본 쿼리 데이터 + LLM 검증 결과를 묶어서 저장
            verified_reports.append({
                "query_data": violation,
                "llm_verification": llm_result.model_dump()
            })

        return {"contradictions": verified_reports} # 임시로 dict 리스트 반환

    # ==========================================
    # 3. LangGraph 오케스트레이션 조립
    # ==========================================
    def _build_graph(self):
        """노드와 엣지를 연결하여 상태 머신(Graph)을 생성합니다."""
        workflow = StateGraph(AgentState)

        # 노드 등록
        workflow.add_node("ingest", self.node_ingest)
        workflow.add_node("extract", self.node_extract)
        workflow.add_node("normalize", self.node_normalize)
        workflow.add_node("detect", self.node_detect)

        # 엣지 연결 (순서 정의)
        workflow.add_edge(START, "ingest")
        workflow.add_edge("ingest", "extract")
        workflow.add_edge("extract", "normalize")
        workflow.add_edge("normalize", "detect")
        workflow.add_edge("detect", END)

        return workflow.compile()

    # ==========================================
    # 4. 외부 노출용 실행 메서드
    # ==========================================
    async def analyze_manuscript(self, text: str, source_type: str = "scenario") -> Dict[str, Any]:
        """
        [진입점] 그래프를 실행하여 원고를 분석합니다.
        """
        logger.info("Starting LangGraph Full Analysis Pipeline")
        source_id = f"src-{uuid.uuid4().hex[:8]}"

        # 초기 상태(State) 설정
        initial_state = {
            "text": text,
            "source_type": source_type,
            "source_id": source_id,
            "chunks": [],
            "extractions":[],
            "normalized_data": None,
            "contradictions":[]
        }

        # LangGraph 비동기 실행 (ainvoke)
        final_state = await self.graph.ainvoke(initial_state)
        
        logger.info("Pipeline Complete", 
                    extracted_characters=len(final_state["normalized_data"].characters) if final_state["normalized_data"] else 0)

        return {
            "status": "success",
            "extracted_entities": final_state["normalized_data"].characters if final_state["normalized_data"] else[],
            "contradictions": final_state["contradictions"]
        }

        self._graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(AgentState)

        builder.add_node("extract", _extract)
        builder.add_node("normalize", _normalize)
        builder.add_node("snapshot", _snapshot)
        builder.add_node("materialize", _materialize)
        builder.add_node("detect", _detect)
        builder.add_node("respond", _respond)

        builder.set_entry_point("extract")
        builder.add_edge("extract", "normalize")
        builder.add_edge("normalize", "snapshot")
        builder.add_edge("snapshot", "materialize")
        builder.add_edge("materialize", "detect")
        builder.add_edge("detect", "respond")
        builder.add_edge("respond", END)

        return builder.compile()

    async def analyze_manuscript(self, manuscript: ManuscriptInput) -> AnalysisResponse:
        """원고 분석 전체 파이프라인 (LangGraph 오케스트레이션).

        흐름: extract → normalize → snapshot → materialize → detect → respond
        스냅샷 격리: canonical graph는 respond 이후 폐기, 절대 불변.
        """
        logger.info("agent_start", title=manuscript.title)

        initial: AgentState = {
            "manuscript": manuscript,
            "raw_extraction": None,
            "normalized": None,
            "snapshot": None,
            "violations": {},
            "result": None,
            "error": None,
        }

        final = await self._graph.ainvoke(initial)

        result = final.get("result")
        if result is None:
            logger.warning("agent_no_result")
            return AnalysisResponse(contradictions=[], confirmations=[], total=0)

        logger.info(
            "agent_complete",
            contradictions=len(result.contradictions),
            confirmations=len(result.confirmations),
        )
        return result

