import re
import uuid
import io
import structlog
from typing import List, Optional

try:
    import tiktoken  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    tiktoken = None

try:
    import fitz  # type: ignore  # PyMuPDF
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    fitz = None

from PyPDF2 import PdfReader

from app.models.api import DocumentChunk, SourceLocation

logger = structlog.get_logger(__name__)

class IngestService:
    def __init__(self):
        # 변경 주석: tiktoken 미설치 환경에서도 동작하도록 fallback 토크나이저 추가
        self.tokenizer = tiktoken.get_encoding("cl100k_base") if tiktoken else None
        self.chunk_size = 500
        self.chunk_overlap = 100

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

    def _create_chunks(self, text: str, source_id: str, source_name: str, start_page: int = 1) -> List[DocumentChunk]:
        if not text or len(text.strip()) < 10:
            return []

        tokens = self._tokenize(text)
        chunks = []
        current_chapter = self._detect_chapter_or_scene(text[:300])
        
        if not tokens:
            return []

        for i in range(0, len(tokens), self.chunk_size - self.chunk_overlap):
            chunk_tokens = tokens[i : i + self.chunk_size]
            chunk_text = self._detokenize(chunk_tokens)
            
            new_chapter = self._detect_chapter_or_scene(chunk_text[:150])
            if new_chapter:
                current_chapter = new_chapter

            # 1. 딕셔너리 형태로 데이터를 먼저 준비합니다.
            location_data = {
                "source_id": source_id,
                "source_name": source_name,
                "page": start_page,
                "chapter": current_chapter,
                "line_range": None
            }

            try:
                # 변경 주석: location을 명시적 SourceLocation 객체로 생성해 타입 안정성 강화
                location = SourceLocation(**location_data)
                chunk = DocumentChunk(
                    id=str(uuid.uuid4()),
                    source_id=source_id,
                    chunk_index=len(chunks),
                    content=chunk_text,
                    location=location
                )
                chunks.append(chunk)
            except Exception as e:
                # 에러 디버깅을 위해 상세 출력
                logger.error("Chunk creation failed", error=str(e))
                continue
            
            if i + self.chunk_size >= len(tokens):
                break
                
        return chunks

    async def process_file(self, file_content: bytes, filename: str, source_id: str) -> List[DocumentChunk]:
        """파일 타입에 따라 청크를 생성합니다."""
        if filename.lower().endswith(".pdf"):
            return await self._parse_pdf_content(file_content, filename, source_id)
        else:
            try:
                text = file_content.decode("utf-8")
            except UnicodeDecodeError:
                text = file_content.decode("cp949", errors="ignore") # 한국어 인코딩 대응
            return self._create_chunks(text, source_id, filename)

    async def _parse_pdf_content(self, content: bytes, filename: str, source_id: str) -> List[DocumentChunk]:
        """PDF 텍스트 추출.

        변경 주석: PyMuPDF 우선 사용, 미설치 시 PyPDF2로 fallback.
        """
        all_chunks = []
        try:
            if fitz:
                doc = fitz.open(stream=content, filetype="pdf")
                for i, page in enumerate(doc):
                    page_text = page.get_text("text")
                    if not page_text or len(page_text.strip()) < 5:
                        continue
                    page_chunks = self._create_chunks(
                        page_text, source_id, filename, start_page=i + 1
                    )
                    all_chunks.extend(page_chunks)
                doc.close()
            else:
                reader = PdfReader(io.BytesIO(content))
                for i, page in enumerate(reader.pages):
                    page_text = page.extract_text() or ""
                    if len(page_text.strip()) < 5:
                        continue
                    page_chunks = self._create_chunks(
                        page_text, source_id, filename, start_page=i + 1
                    )
                    all_chunks.extend(page_chunks)
        except Exception as e:
            logger.error("PDF parsing error", error=str(e))
            
        return all_chunks
