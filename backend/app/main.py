from typing import List, Optional, Dict, Any
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import structlog

from app.config import settings
from app.models.api import (
    ManuscriptInput, AnalysisResponse, ContradictionReport, 
    KBStats, VersionInfo, IngestResponse, ErrorResponse
)
from app.models.vertices import UserConfirmation
from app.models.enums import ContradictionType, Severity, ConfirmationStatus

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
    """3분류(worldview/settings/scenario) 업로드 (Dummy)"""
    return IngestResponse(
        source_id="dummy-source-123",
        source_name=file.filename or "unknown.txt",
        status="processed",
        stats={"chunks": 10},
        extracted_entities=5
    )

@app.get("/api/sources")
def list_sources():
    """소스 목록 (Dummy)"""
    return [
        {"id": "doc1", "name": "세계관_설정.txt", "type": "worldview", "status": "indexed"},
        {"id": "doc2", "name": "캐릭터_설정집.pdf", "type": "settings", "status": "indexed"},
    ]

@app.delete("/api/sources/{source_id}")
def delete_source(source_id: str):
    """소스 삭제 + 정리 (Dummy)"""
    return {"status": "success", "message": f"Source {source_id} deleted."}

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
def analyze_manuscript(manuscript: ManuscriptInput):
    """원고 기반 임시 모순 탐지 (Dummy)"""
    # 더미 모순 리포트 1개 생성
    dummy_report = ContradictionReport(
        id="report-001",
        type=ContradictionType.TIMELINE,
        severity=Severity.CRITICAL,
        character_name="형사 A",
        description="죽은 줄 알았던 캐릭터가 5년 전 과거 회상 없이 현재에 등장합니다.",
        confidence=0.85,
        suggestion="단순 설정 오류라면 등장 씬을 수정하고, 복선이라면 User Confirmation을 통해 승인해 주세요."
    )
    
    # 더미 User Confirmation 1개 생성
    dummy_confirmation = UserConfirmation(
        id="11111111-1111-1111-1111-111111111111",
        source_id="dummy-source",
        confirmation_type="timeline_ambiguity",
        status=ConfirmationStatus.PENDING,
        question="캐릭터 A와 B의 관계가 이전 장에서는 '원수'였으나 지금은 '협력자'로 묘사됩니다. 의도된 변화입니까?",
        context_summary="A와 B가 협력하여 함정을 파는 장면",
        source_excerpts=[]
    )
    
    return AnalysisResponse.from_contradictions(
        contradictions=[dummy_report],
        confirmations=[dummy_confirmation],
        processing_time_ms=1500
    )

@app.post("/api/scan", response_model=AnalysisResponse)
def scan_database():
    """그래프 전수조사 (Dummy)"""
    return AnalysisResponse(contradictions=[], confirmations=[], total=0)

# ==========================================
# 4. 사용자 확인 (Review Workflow) API
# ==========================================
@app.get("/api/confirmations", response_model=List[UserConfirmation])
def list_confirmations():
    """미해결 확인(Confirmation) 목록 반환 (Dummy)"""
    return []

class ResolveConfirmationRequest(BaseModel):
    decision: str
    user_response: Optional[str] = None

@app.post("/api/confirmations/{confirmation_id}/resolve")
def resolve_confirmation(confirmation_id: str, req: ResolveConfirmationRequest):
    """사용자 피드백에 따른 해결 처리 (Dummy)"""
    return {"status": "success", "confirmation_id": confirmation_id, "decision": req.decision}

# ==========================================
# 5. 수정 반영(Fixes) 및 버전 API
# ==========================================
class StageFixRequest(BaseModel):
    contradiction_id: str
    original_text: str
    fixed_text: str

@app.post("/api/fixes/stage")
def stage_fix(req: StageFixRequest):
    """수정사항 스테이징 (Dummy)"""
    return {"status": "staged", "contradiction_id": req.contradiction_id}

@app.post("/api/fixes/push", response_model=VersionInfo)
def push_fixes():
    """스테이징된 수정사항 일괄 반영 후 새 버전 생성 (Dummy)"""
    return VersionInfo(
        id="v-1234",
        version="v1.1",
        date="2026-03-18",
        fixes_count=2,
        description="캐릭터 설정 충돌 수정"
    )

@app.get("/api/versions", response_model=List[VersionInfo])
def list_versions():
    """이력 조회 (Dummy)"""
    return [
        VersionInfo(id="v-0001", version="v1.0", date="2026-03-01", fixes_count=0, description="초안"),
    ]

@app.get("/api/versions/{version_id}")
def get_version_detail(version_id: str):
    """특정 버전의 원고 상세 내용 반환 (Dummy)"""
    return {"version_id": version_id, "content": "이것은 Dummy 버전의 원고 내용입니다."}

@app.get("/api/versions/{v_a}/diff/{v_b}")
def compare_versions(v_a: str, v_b: str):
    """두 버전 간 차이 반환 (Dummy)"""
    return {"diff": f"Differences between {v_a} and {v_b}"}

# ==========================================
# 6. 통계 조회 API
# ==========================================
@app.get("/api/kb/stats", response_model=KBStats)
def get_kb_stats():
    """Knowledge Base 통계 조회 (Dummy)"""
    return KBStats(
        characters=10,
        facts=50,
        relationships=15,
        events=20,
        traits=25,
        locations=5,
        items=3,
        organizations=2,
        sources=3,
        confirmations=1
    )

@app.get("/api/characters")
def list_characters():
    """캐릭터 목록 반환 (Dummy)"""
    return [{"id": "char-1", "name": "주인공"}, {"id": "char-2", "name": "악당"}]

@app.get("/api/characters/{character_id}/knowledge")
def get_character_knowledge(character_id: str):
    """특정 캐릭터의 지식 목록 반환 (Dummy)"""
    return {"character_id": character_id, "knowledge": []}

@app.get("/api/facts")
def list_facts():
    """사실(Facts) 목록 반환 (Dummy)"""
    return [{"id": "fact-1", "content": "마법은 존재한다."}]

@app.get("/api/events")
def list_events():
    """이벤트 목록 반환 (Dummy)"""
    return [{"id": "evt-1", "description": "주인공이 검을 뽑음"}]

# ==========================================
# 7. AI 질의 API
# ==========================================
class AIQueryRequest(BaseModel):
    query: str

@app.post("/api/ai/query")
def query_ai(req: AIQueryRequest):
    """자유 형식 AI 지식베이스 질의 (Dummy)"""
    return {
        "answer": f"'{req.query}'에 대한 더미 답변입니다.",
        "sources": ["세계관_설정.txt (p.10)"]
    }

