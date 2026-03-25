from typing import List, Literal, Optional, Any
from pydantic import BaseModel, Field

from app.models.enums import SourceType, ContradictionType, Severity, ConfirmationStatus
from app.models.vertices import UserConfirmation

# ==========================================
# API Request / Input Models
# ==========================================

class ManuscriptInput(BaseModel):
    content: str
    title: str

# ==========================================
# Ingestion / Search Models
# ==========================================

class ChunkLocation(BaseModel):
    """DocumentChunk의 위치 메타데이터 (API 계층 전용). 도메인 모델 enums.SourceLocation과 별도."""
    source_id: str
    source_name: str
    page: Optional[int] = None
    chapter: Optional[str] = None
    line_range: Optional[tuple[int, int]] = None

class DocumentChunk(BaseModel):
    id: str
    source_id: str
    chunk_index: int
    content: str
    location: ChunkLocation

class PipelineError(BaseModel):
    """파이프라인 단계별 오류 정보"""
    layer: str              # "extraction", "normalization", "materialize", "search", "detect" 등
    message: str            # 오류 메시지
    recoverable: bool       # True이면 해당 단계를 건너뛰고 계속 진행됨

class IngestResponse(BaseModel):
    source_id: str
    source_name: str
    file_path: str = ""
    status: str
    stats: dict[str, Any]
    extracted_entities: int
    content_filter_blocked_chunks: List[str] = Field(default_factory=list)
    pipeline_errors: List[PipelineError] = Field(default_factory=list)

# ==========================================
# Analysis & Detection Models
# ==========================================

class EvidenceItem(BaseModel):
    source_name: str
    source_location: str
    text: str

class ContradictionReport(BaseModel):
    id: str
    type: ContradictionType
    severity: Severity
    hard_or_soft: Literal["hard", "soft"] = "soft"
    character_id: Optional[str] = None
    character_name: Optional[str] = None
    location: Optional[str] = None
    dialogue: Optional[str] = None
    description: str
    evidence: List[EvidenceItem] = Field(default_factory=list)
    confidence: float
    suggestion: Optional[str] = None
    alternative: Optional[str] = None
    needs_user_input: bool = False
    user_question: Optional[str] = None
    original_text: Optional[str] = None
    chunk_id: Optional[str] = None
    chunk_content: Optional[str] = None

class AnalysisResponse(BaseModel):
    contradictions: List[ContradictionReport] = Field(default_factory=list)
    confirmations: List[UserConfirmation] = Field(default_factory=list)
    total: int = 0
    by_severity: dict[Severity, int] = Field(default_factory=dict)
    by_type: dict[str, int] = Field(default_factory=dict)
    hard_count: int = 0
    soft_count: int = 0
    processing_time_ms: int = 0
    llm_cost: Optional[dict] = None
    pipeline_errors: List[PipelineError] = Field(default_factory=list)

    @classmethod
    def from_contradictions(cls, contradictions: List[ContradictionReport], confirmations: List[UserConfirmation], processing_time_ms: int = 0) -> 'AnalysisResponse':
        total = len(contradictions) + len(confirmations)

        by_sev: dict[Severity, int] = {}
        by_type: dict[str, int] = {}
        hard_count = 0
        soft_count = 0
        for c in contradictions:
            by_sev[c.severity] = by_sev.get(c.severity, 0) + 1
            type_val = c.type.value if hasattr(c.type, 'value') else c.type
            by_type[type_val] = by_type.get(type_val, 0) + 1
            if c.hard_or_soft == "hard":
                hard_count += 1
            else:
                soft_count += 1

        return cls(
            contradictions=contradictions,
            confirmations=confirmations,
            total=total,
            by_severity=by_sev,
            by_type=by_type,
            hard_count=hard_count,
            soft_count=soft_count,
            processing_time_ms=processing_time_ms,
        )

# ==========================================
# Knowledge Base (KB) & Version Models
# ==========================================

class KBStats(BaseModel):
    characters: int = 0
    facts: int = 0
    relationships: int = 0
    events: int = 0
    traits: int = 0
    locations: int = 0
    items: int = 0
    organizations: int = 0
    sources: int = 0
    confirmations: int = 0

class VersionInfo(BaseModel):
    id: str
    version: str
    date: str
    fixes_count: int
    description: str
    snapshot_path: str = ""
    src: str = ""  # 소스 파일명 (프론트엔드 버전 카드 배지용)
    pipeline_errors: List[PipelineError] = Field(default_factory=list)

class ErrorResponse(BaseModel):
    detail: str
    error_code: str
