import uuid
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
import structlog

from app.config import settings
from app.models.api import (
    ManuscriptInput, AnalysisResponse, ContradictionReport, 
    KBStats, VersionInfo, IngestResponse, ErrorResponse
)
from app.models.vertices import UserConfirmation, Source
from app.models.enums import ContradictionType, Severity, ConfirmationStatus, SourceType
from app.services.ingest import IngestService
from app.services.storage import StorageService, get_global_storage
from app.services.agent import ContiCheckAgent
from app.services.detection import DetectionService
from app.services.extraction import ExtractionService
from app.services.normalization import NormalizationService
from app.services.graph import get_graph_service, _vertex_to_dict
from app.services.confirmation import ConfirmationService, ConfirmationNotFoundError, AlreadyResolvedError
from app.services.search import get_search_service
from app.services.version import VersionService

# VersionService 싱글턴 (스테이징 큐 + 버전 이력 유지)
_version_service: Optional[VersionService] = None

def get_version_service() -> VersionService:
    global _version_service
    if _version_service is None:
        _version_service = VersionService(
            graph_service=get_graph_service(),
            ingest_service=IngestService(),
            extraction_service=ExtractionService(),
            normalization_service=NormalizationService(),
            search_service=get_search_service(),
            storage_service=get_global_storage(),
        )
    return _version_service

logger = structlog.get_logger(__name__)

app = FastAPI(
    title=settings.app_name,
    description="시나리오 정합성 검증 시스템 POC (ContiCheck) 백엔드",
    version="0.1.0",
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": settings.app_name}

# ==========================================
# 1. 소스 관리 API
# ==========================================
@app.post("/api/sources/upload", response_model=IngestResponse)
async def upload_source(
    file: UploadFile = File(...),
    source_type: str = Form(description="worldview, settings, scenario 중 하나")
):
    content = await file.read()
    source_id = f"src-{uuid.uuid4().hex[:8]}"
    filename = file.filename or "unknown"

    # 1) 파일 저장 + 청킹 (IngestResult.file_path = Blob URL or 로컬 경로)
    ingest_service = IngestService()
    ingest_result = await ingest_service.process_file(
        file_content=content,
        filename=filename,
        source_id=source_id,
        source_type=source_type,
    )

    # 2) Source vertex를 그래프에 저장 (file_path 포함 — download/delete의 핵심 키)
    # vertex id를 source_id("src-xxx")와 동일하게 설정 → get_vertex(source_id) 조회 일치
    graph = get_graph_service()
    source_vertex = Source(
        source_id=source_id,
        source_type=SourceType(source_type),
        name=filename,
        file_path=ingest_result.file_path,
    )
    source_dict = _vertex_to_dict(source_vertex)
    source_dict["id"] = source_id
    graph.add_source(source_dict)

    # 3) Extract → Normalize → Materialize → Search 인덱싱
    extraction_svc = ExtractionService()
    extraction_results = await extraction_svc.extract_from_chunks(
        ingest_result.chunks, source_type
    )

    normalization_svc = NormalizationService()
    normalization_result = await normalization_svc.normalize(extraction_results)

    graph.materialize(normalization_result, source_vertex)

    search_svc = get_search_service()
    await search_svc.index_chunks(source_id=source_id, chunks=ingest_result.chunks)

    extracted_entities = (
        len(normalization_result.characters)
        + len(normalization_result.facts)
        + len(normalization_result.events)
    )
    logger.info(
        "source_uploaded",
        source_id=source_id,
        file_path=ingest_result.file_path,
        extracted_entities=extracted_entities,
    )

    return IngestResponse(
        source_id=source_id,
        source_name=filename,
        file_path=ingest_result.file_path,
        status="processed",
        stats={"chunks": len(ingest_result.chunks)},
        extracted_entities=extracted_entities,
    )

@app.get("/api/sources")
def list_sources(source_type: Optional[str] = None):
    """소스 목록"""
    graph = get_graph_service()
    sources = graph.list_sources()
    if source_type:
        sources = [s for s in sources if s.get("source_type") == source_type]
    return sources

@app.delete("/api/sources/{source_id}")
async def delete_source(source_id: str):
    """소스 삭제 — graph에서 vertex/edge 제거 + StorageService.delete_file(file_path)"""
    graph = get_graph_service()
    # 그래프 삭제 전에 file_path 확보
    source_vertex = graph.get_vertex(source_id, "source")
    file_path = (source_vertex or {}).get("file_path", "")

    graph.remove_source(source_id)

    if file_path:
        storage: StorageService = get_global_storage()
        try:
            await storage.delete_file(file_path)
        except Exception as e:
            logger.warning("delete_source_file_failed", source_id=source_id, error=str(e))

    return {"status": "success", "message": f"Source {source_id} deleted."}

@app.put("/api/sources/{source_id}")
async def reupload_source(
    source_id: str,
    file: UploadFile = File(...),
):
    """기존 소스 파일 교체 — source_id 유지, 그래프/인덱스 증분 재구축"""
    graph = get_graph_service()
    source_vertex = graph.get_vertex(source_id, "source")
    if not source_vertex:
        raise HTTPException(status_code=404, detail=f"소스를 찾을 수 없습니다: {source_id}")

    old_file_path = source_vertex.get("file_path", "")
    source_type = source_vertex.get("source_type", "scenario")

    content = await file.read()
    filename = file.filename or "unknown"
    storage: StorageService = get_global_storage()

    # 기존 파일 삭제
    if old_file_path:
        try:
            await storage.delete_file(old_file_path)
        except Exception as e:
            logger.warning("reupload_delete_old_failed", source_id=source_id, error=str(e))

    # 새 파일 저장 + 파싱 (동일 source_id 재사용)
    ingest_service = IngestService()
    ingest_result = await ingest_service.process_file(
        file_content=content,
        filename=filename,
        source_id=source_id,
        source_type=source_type,
    )

    # Source vertex file_path + name 업데이트
    graph.patch_vertex(
        vertex_id=source_id,
        partition_key="source",
        fields={"file_path": ingest_result.file_path, "name": filename},
    )

    # Search 인덱스 정리 후 재인덱싱
    search_svc = get_search_service()
    try:
        await search_svc.remove_source(source_id)
    except Exception as e:
        logger.warning("reupload_remove_index_failed", source_id=source_id, error=str(e))

    # Extract → Normalize → Materialize → Index
    extraction_svc = ExtractionService()
    extraction_results = await extraction_svc.extract_from_chunks(
        ingest_result.chunks, source_type
    )

    normalization_svc = NormalizationService()
    normalization_result = await normalization_svc.normalize(extraction_results)

    source_obj = Source(
        source_id=source_id,
        source_type=SourceType(source_type),
        name=filename,
        file_path=ingest_result.file_path,
    )
    graph.materialize(normalization_result, source_obj)

    await search_svc.index_chunks(source_id=source_id, chunks=ingest_result.chunks)

    extracted_entities = (
        len(normalization_result.characters)
        + len(normalization_result.facts)
        + len(normalization_result.events)
    )
    logger.info("source_reuploaded", source_id=source_id, file_path=ingest_result.file_path)

    return IngestResponse(
        source_id=source_id,
        source_name=filename,
        file_path=ingest_result.file_path,
        status="reuploaded",
        stats={"chunks": len(ingest_result.chunks)},
        extracted_entities=extracted_entities,
    )

@app.get("/api/sources/{source_id}/download")
async def download_source(source_id: str):
    """원본 파일 다운로드 — Source vertex의 file_path로 StorageService.get_file() 호출"""
    graph = get_graph_service()
    source_vertex = graph.get_vertex(source_id, "source")
    if not source_vertex:
        raise HTTPException(status_code=404, detail=f"소스를 찾을 수 없습니다: {source_id}")
    file_path = source_vertex.get("file_path", "")
    if not file_path:
        raise HTTPException(status_code=404, detail=f"파일 경로가 없습니다: {source_id}")

    storage: StorageService = get_global_storage()
    try:
        file_bytes = await storage.get_file(file_path)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"파일을 찾을 수 없습니다: {e}")
    return Response(content=file_bytes, media_type="application/octet-stream")

# ==========================================
# 2. GraphRAG 구축 API
# ==========================================
class BuildGraphRequest(BaseModel):
    track: str

@app.post("/api/graph/build")
def build_graph(req: BuildGraphRequest):
    """트랙(ws/sc) 기반 GraphRAG 구축 시작 (Dummy)"""
    return {"status": "started", "track": req.track, "job_id": "job-idx-999"}

@app.get("/api/graph/status")
def get_graph_status():
    """구축 상태 확인 (Dummy)"""
    return {"status": "completed", "progress": 100}

# ==========================================
# 3. 모순 탐지 API
# ==========================================
@app.post("/api/analyze", response_model=AnalysisResponse)
async def analyze_manuscript(manuscript: ManuscriptInput):
    """원고 기반 모순 탐지 — ContiCheckAgent 5계층 파이프라인 실행"""
    try:
        agent = ContiCheckAgent()
        return await agent.analyze_manuscript(manuscript)
    except Exception as e:
        logger.error("analyze_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"분석 실패: {e}")

@app.post("/api/scan", response_model=AnalysisResponse)
async def scan_database():
    """그래프 전수조사 — canonical graph 전체 대상 모순 탐지"""
    try:
        graph = get_graph_service()
        svc = DetectionService()
        return await svc.full_scan(graph)
    except Exception as e:
        logger.error("scan_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"전수조사 실패: {e}")

# ==========================================
# 4. 사용자 확인 (Review Workflow) API
# ==========================================
@app.get("/api/confirmations", response_model=List[UserConfirmation])
async def list_confirmations():
    """미해결 확인(Confirmation) 목록 반환"""
    graph = get_graph_service()
    search = get_search_service()
    svc = ConfirmationService(graph, search)
    try:
        return await svc.list_pending()
    except Exception as e:
        logger.error("list_confirmations_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"목록 조회 실패: {e}")

class ResolveConfirmationRequest(BaseModel):
    decision: str
    user_response: Optional[str] = None

@app.post("/api/confirmations/{confirmation_id}/resolve")
async def resolve_confirmation(confirmation_id: str, req: ResolveConfirmationRequest):
    """사용자 피드백에 따른 해결 처리 — 피드백 루프 실행"""
    graph = get_graph_service()
    search = get_search_service()
    svc = ConfirmationService(graph, search)
    try:
        updated = await svc.resolve(
            confirmation_id=confirmation_id,
            user_response=req.user_response or "",
            decision=req.decision,
        )
        return {"status": "success", "confirmation_id": confirmation_id, "decision": req.decision, "final_status": updated.status}
    except ConfirmationNotFoundError:
        raise HTTPException(status_code=404, detail=f"확인을 찾을 수 없습니다: {confirmation_id}")
    except AlreadyResolvedError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("resolve_confirmation_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"해결 처리 실패: {e}")

# ==========================================
# 5. 수정 반영(Fixes) 및 버전 API
# ==========================================
class StageFixRequest(BaseModel):
    contradiction_id: str
    original_text: Optional[str] = ""
    fixed_text: Optional[str] = ""
    is_intentional: bool = False
    intent_note: str = ""

@app.post("/api/fixes/stage")
async def stage_fix(req: StageFixRequest):
    """수정사항 스테이징. is_intentional=True이면 텍스트 교체 없이 의도 인정으로 처리."""
    try:
        svc = get_version_service()
        fix = await svc.stage_fix(
            contradiction_id=req.contradiction_id,
            original_text=req.original_text or "",
            fixed_text=req.fixed_text or "",
            is_intentional=req.is_intentional,
            intent_note=req.intent_note,
        )
        return {"status": "staged", "contradiction_id": fix.contradiction_id, "staged_at": fix.staged_at.isoformat(), "is_intentional": fix.is_intentional}
    except Exception as e:
        logger.error("stage_fix_failed", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))

class PushFixesRequest(BaseModel):
    source_id: str
    description: Optional[str] = ""

@app.post("/api/fixes/push", response_model=VersionInfo)
async def push_fixes(req: PushFixesRequest):
    """스테이징된 수정사항 일괄 반영 후 새 버전 생성"""
    try:
        svc = get_version_service()
        return await svc.push_staged_fixes(source_id=req.source_id, description=req.description or "")
    except Exception as e:
        logger.error("push_fixes_failed", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/versions", response_model=List[VersionInfo])
async def list_versions():
    """버전 이력 조회"""
    svc = get_version_service()
    return await svc.list_versions()

@app.get("/api/versions/{version_id}/content")
async def get_version_content(version_id: str):
    """해당 버전의 원고 텍스트 반환 — VersionService.get_version() 위임 (source_id 내부 조회)"""
    try:
        svc = get_version_service()
        text = await svc.get_version(version_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"버전을 찾을 수 없습니다: {e}")
    return {"content": text}

@app.get("/api/versions/{version_id}")
async def get_version_detail(version_id: str):
    """특정 버전의 원고 내용 반환"""
    try:
        svc = get_version_service()
        content = await svc.get_version(version_id)
        return {"version_id": version_id, "content": content}
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.get("/api/versions/{v_a}/diff/{v_b}")
async def compare_versions(v_a: str, v_b: str):
    """두 버전 간 차이 반환"""
    try:
        svc = get_version_service()
        diff = await svc.diff_versions(v_a, v_b)
        return {"diff": diff}
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

# ==========================================
# 6. 통계 조회 API
# ==========================================
@app.get("/api/kb/stats", response_model=KBStats)
def get_kb_stats():
    """Knowledge Base 통계 조회"""
    graph = get_graph_service()
    return graph.get_stats()

@app.get("/api/characters")
def list_characters():
    """캐릭터 목록 반환"""
    graph = get_graph_service()
    return graph.list_characters()

@app.get("/api/characters/{character_id}/knowledge")
def get_character_knowledge(character_id: str):
    """특정 캐릭터의 지식 목록 반환 (Dummy)"""
    return {"character_id": character_id, "knowledge": []}

@app.get("/api/facts")
def list_facts():
    """사실(Facts) 목록 반환"""
    graph = get_graph_service()
    return graph.list_facts()

@app.get("/api/events")
def list_events():
    """이벤트 목록 반환"""
    graph = get_graph_service()
    return graph.list_events()

# ==========================================
# 7. AI 질의 API
# ==========================================
class AIQueryRequest(BaseModel):
    query: str

@app.post("/api/ai/query")
async def query_ai(req: AIQueryRequest):
    """자유 형식 AI 지식베이스 질의"""
    search_svc = get_search_service()
    evidence = await search_svc.search_context(req.query)
    sources = [f"{e.source_name} ({e.source_location})" for e in evidence if e.source_name]
    context = "\n".join(e.text for e in evidence) if evidence else ""
    answer = f"[{req.query}] 관련 컨텍스트:\n{context}" if context else f"'{req.query}'에 대한 관련 정보를 찾을 수 없습니다."
    return {"answer": answer, "sources": sources}

