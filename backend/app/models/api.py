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

class SourceLocation(BaseModel):
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
    location: SourceLocation

class IngestResponse(BaseModel):
    source_id: str
    source_name: str
    file_path: str = ""
    status: str
    stats: dict[str, Any]
    extracted_entities: int

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

class AnalysisResponse(BaseModel):
    contradictions: List[ContradictionReport] = Field(default_factory=list)
    confirmations: List[UserConfirmation] = Field(default_factory=list)
    total: int = 0
    by_severity: dict[Severity, int] = Field(default_factory=dict)
    by_type: dict[str, int] = Field(default_factory=dict)
    hard_count: int = 0
    soft_count: int = 0
    processing_time_ms: int = 0

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

class ErrorResponse(BaseModel):
    detail: str
    error_code: str
