"""
ingest.py — 계층 1: 문서 파싱 + 청킹

[StorageService 연동 변경사항]
  - __init__에 storage: StorageService 파라미터 추가
  - process_file() 시작 시 storage.save_file() 호출 → file_path 반환
  - 반환 타입이 list[DocumentChunk] → IngestResult(chunks, file_path)로 변경
  - 호출자(main.py)가 file_path를 Source.file_path 필드에 기록

흐름:
  bytes → storage.save_file() → 영구 저장
  bytes → 파싱/청킹 → list[DocumentChunk]
  둘 다 IngestResult에 묶어 반환
"""

import re
import uuid
import io
import structlog
from dataclasses import dataclass, field
from typing import List, Optional

try:
    import tiktoken  # type: ignore
except ModuleNotFoundError:
    tiktoken = None

try:
    import fitz  # type: ignore  # PyMuPDF
except ModuleNotFoundError:
    fitz = None

from PyPDF2 import PdfReader

from app.models.api import DocumentChunk, SourceLocation

# ── [신규] StorageService 임포트 ─────────────────────────────
from app.services.storage import StorageService, get_global_storage

logger = structlog.get_logger(__name__)


# ── [신규] 반환 타입 정의 ─────────────────────────────────────
@dataclass
class IngestResult:
    """
    process_file()의 반환 타입.

    Attributes
    ----------
    chunks : list[DocumentChunk]
        파싱된 청크 목록 → ExtractionService로 전달
    file_path : str
        StorageService가 반환한 영구 저장 경로.
        호출자(main.py)가 Source.file_path에 반드시 기록해야 합니다.
        이후 VersionService가 get_file_text(file_path)로 원고를 읽습니다.
    """
    chunks: List[DocumentChunk] = field(default_factory=list)
    file_path: str = ""


class IngestService:
    """
    파일 업로드 → 영구 저장 → 파싱 → 청킹 담당.

    Parameters
    ----------
    storage : StorageService, optional
        주입할 스토리지 서비스.
        None이면 get_global_storage()로 자동 생성합니다 (싱글턴).

    사용 예::

        # 기본 사용 (로컬 스토리지 자동)
        ingest = IngestService()

        # 테스트용 mock 주입
        ingest = IngestService(storage=MockStorageService())

        result = await ingest.process_file(
            file_content=file_bytes,
            filename="설정집.pdf",
            source_id="src-001",
            source_type="settings",
        )

        # 호출자가 해야 할 일:
        source.file_path = result.file_path   # ← Source vertex에 기록
        chunks = result.chunks                 # ← ExtractionService로 전달
    """

    def __init__(self, storage: Optional[StorageService] = None) -> None:
        # ── [변경] storage 주입 (없으면 전역 싱글턴 사용) ──────
        self.storage: StorageService = storage or get_global_storage()

        self.tokenizer = tiktoken.get_encoding("cl100k_base") if tiktoken else None
        self.chunk_size = 500
        self.chunk_overlap = 100

    # ── 내부 헬퍼 (변경 없음) ──────────────────────────────────

    def _tokenize(self, text: str) -> List[str]:
        if self.tokenizer:
            return self.tokenizer.encode(text)
        return re.findall(r"\S+", text)

    def _detokenize(self, tokens: List[str]) -> str:
        if self.tokenizer:
            return self.tokenizer.decode(tokens)
        return " ".join(tokens)

    def _detect_chapter_or_scene(self, text: str) -> Optional[str]:
        patterns = [
            r"(#\s*Scene\s*\d+)", r"(Scene\s*\d+)", r"(S#\d+)",
            r"(#\s*Chapter\s*\d+)", r"(제\s*\d+\s*[장|화])", r"(EP\d+)"
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _create_chunks(
        self,
        text: str,
        source_id: str,
        source_name: str,
        start_page: int = 1,
    ) -> List[DocumentChunk]:
        if not text or len(text.strip()) < 10:
            return []

        tokens = self._tokenize(text)
        if not tokens:
            return []

        chunks = []
        current_chapter = self._detect_chapter_or_scene(text[:300])

        for i in range(0, len(tokens), self.chunk_size - self.chunk_overlap):
            chunk_tokens = tokens[i: i + self.chunk_size]
            chunk_text = self._detokenize(chunk_tokens)

            new_chapter = self._detect_chapter_or_scene(chunk_text[:150])
            if new_chapter:
                current_chapter = new_chapter

            try:
                location = SourceLocation(
                    source_id=source_id,
                    source_name=source_name,
                    page=start_page,
                    chapter=current_chapter,
                    line_range=None,
                )
                chunks.append(DocumentChunk(
                    id=str(uuid.uuid4()),
                    source_id=source_id,
                    chunk_index=len(chunks),
                    content=chunk_text,
                    location=location,
                ))
            except Exception as e:
                logger.error("chunk_creation_failed", error=str(e))
                continue

            if i + self.chunk_size >= len(tokens):
                break

        return chunks

    # ── 핵심 public 메서드 ─────────────────────────────────────

    async def process_file(
        self,
        file_content: bytes,
        filename: str,
        source_id: str,
        source_type: str = "scenario",
    ) -> IngestResult:
        """
        파일을 영구 저장하고 청킹합니다.

        Parameters
        ----------
        file_content : bytes
            업로드된 파일 바이트
        filename : str
            원본 파일명 (예: "설정집.pdf")
        source_id : str
            Source Vertex ID
        source_type : str
            "worldview" | "settings" | "scenario"

        Returns
        -------
        IngestResult
            .file_path → Source.file_path에 기록할 영구 저장 경로
            .chunks    → ExtractionService로 전달할 청크 목록
        """

        # ── STEP 1: 먼저 파일을 영구 저장한다 ─────────────────
        #
        #   storage.save_file()은 파일을 디스크(또는 Blob)에 저장하고
        #   나중에 get_file_text()로 다시 읽을 수 있는 경로를 돌려줍니다.
        #   이 경로를 Source.file_path 필드에 반드시 기록해야
        #   VersionService가 원고 내용을 읽을 수 있습니다.
        #
        file_path = await self.storage.save_file(
            file_content=file_content,
            filename=filename,
            source_id=source_id,
            source_type=source_type,
        )
        logger.info(
            "file_stored_permanently",
            source_id=source_id,
            filename=filename,
            file_path=file_path,
        )

        # ── STEP 2: 같은 bytes로 파싱 + 청킹 ──────────────────
        #
        #   파일은 이미 저장했으므로, 여기서는 메모리에 있는 bytes만
        #   사용합니다. 디스크를 다시 읽지 않습니다.
        #
        if filename.lower().endswith(".pdf"):
            chunks = await self._parse_pdf_content(file_content, filename, source_id)
        else:
            try:
                text = file_content.decode("utf-8")
            except UnicodeDecodeError:
                text = file_content.decode("cp949", errors="ignore")
            chunks = self._create_chunks(text, source_id, filename)

        logger.info(
            "file_chunked",
            source_id=source_id,
            filename=filename,
            total_chunks=len(chunks),
        )

        # ── STEP 3: file_path + chunks를 함께 반환 ─────────────
        return IngestResult(chunks=chunks, file_path=file_path)

    async def _parse_pdf_content(
        self,
        content: bytes,
        filename: str,
        source_id: str,
    ) -> List[DocumentChunk]:
        """PDF 텍스트 추출 (PyMuPDF 우선, PyPDF2 fallback)."""
        all_chunks = []
        try:
            if fitz:
                doc = fitz.open(stream=content, filetype="pdf")
                for i, page in enumerate(doc):
                    page_text = page.get_text("text")
                    if not page_text or len(page_text.strip()) < 5:
                        continue
                    all_chunks.extend(
                        self._create_chunks(page_text, source_id, filename, start_page=i + 1)
                    )
                doc.close()
            else:
                reader = PdfReader(io.BytesIO(content))
                for i, page in enumerate(reader.pages):
                    page_text = page.extract_text() or ""
                    if len(page_text.strip()) < 5:
                        continue
                    all_chunks.extend(
                        self._create_chunks(page_text, source_id, filename, start_page=i + 1)
                    )
        except Exception as e:
            logger.error("pdf_parsing_error", error=str(e))
        return all_chunks