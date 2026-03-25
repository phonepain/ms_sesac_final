import structlog
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import StateGraph, END

from app.config import settings
from app.models.api import AnalysisResponse, ManuscriptInput
from app.models.enums import SourceType
from app.models.vertices import Source
from app.services.cost_tracker import get_tracker, reset_tracker
from app.services.detection import DetectionService
from app.services.extraction import ExtractionService
from app.services.graph import InMemoryGraphService, get_graph_service
from app.services.ingest import IngestService
from app.services.normalization import NormalizationService

logger = structlog.get_logger()


# ── LangGraph 상태 정의 ──────────────────────────────────────

class AgentState(TypedDict):
    manuscript: ManuscriptInput
    raw_extraction: Any
    normalized: Any
    snapshot: Any           # InMemoryGraphService 스냅샷 (격리된 복제본)
    violations: Dict        # find_all_violations() 결과
    result: Optional[AnalysisResponse]
    error: Optional[str]
    pipeline_errors: List[Dict]  # [{"layer": str, "message": str, "recoverable": bool}]


# ── 노드 함수 (각 계층) ──────────────────────────────────────

def _add_error(state: AgentState, layer: str, message: str, recoverable: bool) -> List[Dict]:
    """pipeline_errors 리스트에 오류 추가 (immutable 반환)."""
    errors = list(state.get("pipeline_errors") or [])
    errors.append({"layer": layer, "message": message, "recoverable": recoverable})
    return errors


async def _extract(state: AgentState) -> AgentState:
    """계층 1: 텍스트 → RawEntity (청킹 후 배치 처리)"""
    logger.info("langgraph_node", node="extract")
    try:
        ingest = IngestService()
        chunks = ingest.chunk_text(
            text=state["manuscript"].content,
            source_id="agent-manuscript",
            source_name=state["manuscript"].title,
        )
        logger.info("agent_chunks", total=len(chunks))
        svc = ExtractionService()
        raws = await svc.extract_from_chunks(chunks, source_type="scenario")
        return {**state, "raw_extraction": raws}
    except Exception as e:
        logger.error("extract_failed", error=str(e))
        return {
            **state,
            "raw_extraction": [],
            "pipeline_errors": _add_error(state, "extraction", f"추출 실패: {e}", False),
        }


async def _normalize(state: AgentState) -> AgentState:
    """계층 2: RawEntity → NormalizedEntity"""
    logger.info("langgraph_node", node="normalize")
    if not state.get("raw_extraction"):
        return {
            **state,
            "normalized": None,
            "pipeline_errors": _add_error(state, "normalization", "추출 결과가 없어 정규화를 건너뜁니다", True),
        }
    try:
        svc = NormalizationService()
        normalized = await svc.normalize(extractions=state["raw_extraction"])
        return {**state, "normalized": normalized}
    except Exception as e:
        logger.error("normalize_failed", error=str(e))
        return {
            **state,
            "normalized": None,
            "pipeline_errors": _add_error(state, "normalization", f"정규화 실패: {e}", False),
        }


def _snapshot(state: AgentState) -> AgentState:
    """계층 3 준비: canonical graph → In-Memory 스냅샷 복제 (canonical 보호)."""
    logger.info("langgraph_node", node="snapshot")
    try:
        canonical = get_graph_service()
        snapshot = canonical.snapshot_graph()
        return {**state, "snapshot": snapshot}
    except Exception as e:
        logger.error("snapshot_failed", error=str(e))
        return {
            **state,
            "snapshot": None,
            "pipeline_errors": _add_error(state, "snapshot", f"스냅샷 생성 실패: {e}", False),
        }


def _materialize(state: AgentState) -> AgentState:
    """계층 3: NormalizedEntity → 스냅샷에 적재 (canonical graph 불변)"""
    logger.info("langgraph_node", node="materialize")
    snapshot: InMemoryGraphService = state["snapshot"]
    normalized = state["normalized"]

    if not snapshot:
        return {
            **state,
            "pipeline_errors": _add_error(state, "materialize", "스냅샷이 없어 적재를 건너뜁니다", True),
        }
    if not normalized:
        return {
            **state,
            "pipeline_errors": _add_error(state, "materialize", "정규화 결과가 없어 적재를 건너뜁니다", True),
        }

    try:
        source = Source(
            source_id="snapshot",
            source_type=SourceType.MANUSCRIPT,
            name=state["manuscript"].title,
            file_path="",
        )
        snapshot.materialize(normalized, source)
    except Exception as e:
        logger.error("materialize_failed", error=str(e))
        return {
            **state,
            "pipeline_errors": _add_error(state, "materialize", f"그래프 적재 실패: {e}", False),
        }

    return state  # snapshot 객체 자체가 변경됨 (mutable)


def _detect(state: AgentState) -> AgentState:
    """계층 4: 스냅샷에서 7가지 모순 탐지"""
    logger.info("langgraph_node", node="detect")
    snapshot: InMemoryGraphService = state["snapshot"]
    if not snapshot:
        return {
            **state,
            "violations": {},
            "pipeline_errors": _add_error(state, "detect", "스냅샷이 없어 탐지를 건너뜁니다", True),
        }
    try:
        violations = snapshot.find_all_violations()
        logger.info(
            "detect_complete",
            hard=len(violations.get("hard", [])),
            soft=len(violations.get("soft", [])),
        )
        return {**state, "violations": violations}
    except Exception as e:
        logger.error("detect_failed", error=str(e))
        return {
            **state,
            "violations": {},
            "pipeline_errors": _add_error(state, "detect", f"모순 탐지 실패: {e}", False),
        }


async def _respond(state: AgentState) -> AgentState:
    """계층 4: violations → AnalysisResponse + 스냅샷 폐기 (canonical 보호 완료)"""
    logger.info("langgraph_node", node="respond")
    violations = state["violations"]
    errors = state.get("pipeline_errors") or []

    # pipeline_errors → PipelineError 변환
    from app.models.api import PipelineError
    pe_list = [PipelineError(**e) for e in errors]

    # [approve]: 모순이 전혀 없으면 빈 결과 즉시 반환
    if not violations.get("hard") and not violations.get("soft"):
        logger.info("langgraph_node", node="approve", reason="no_violations")
        return {**state, "snapshot": None, "result": AnalysisResponse(
            contradictions=[], confirmations=[], total=0,
            llm_cost=get_tracker().summary(),
            pipeline_errors=pe_list,
        )}

    svc = DetectionService()
    snapshot = state.get("snapshot")
    result = await svc.analyze(violations, graph_service=snapshot)

    # Soft confirmations를 canonical graph에 저장
    # ConfirmationService.list_pending() / resolve()가 그래프를 백엔드로 사용하므로
    # 여기서 저장하지 않으면 GET /api/confirmations → 빈 목록,
    # POST /api/confirmations/{id}/resolve → 404가 된다.
    # UserConfirmation은 분석 원고 데이터가 아닌 워크플로우 상태이므로
    # canonical graph 저장이 스냅샷 격리 원칙에 위배되지 않는다.
    if result.confirmations:
        canonical = get_graph_service()
        for conf in result.confirmations:
            canonical.upsert_vertex(conf)
        logger.info("confirmations_persisted", count=len(result.confirmations))

    # 파이프라인 오류를 result에 합류
    result.pipeline_errors = pe_list

    # 스냅샷 폐기: canonical graph는 한 번도 건드리지 않았음
    return {**state, "snapshot": None, "result": result}


# ── ContiCheckAgent (LangGraph 기반) ─────────────────────────

class ContiCheckAgent:
    def __init__(self):
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
        reset_tracker()

        initial: AgentState = {
            "manuscript": manuscript,
            "raw_extraction": None,
            "normalized": None,
            "snapshot": None,
            "violations": {},
            "result": None,
            "error": None,
            "pipeline_errors": [],
        }

        final = await self._graph.ainvoke(initial)

        result = final.get("result")
        if result is None:
            logger.warning("agent_no_result")
            return AnalysisResponse(contradictions=[], confirmations=[], total=0)

        cost = get_tracker().summary()
        result.llm_cost = cost
        logger.info(
            "agent_complete",
            contradictions=len(result.contradictions),
            confirmations=len(result.confirmations),
            llm_total_tokens=cost["total_tokens"],
            llm_total_cost_usd=cost["total_cost_usd"],
        )
        return result