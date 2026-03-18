# backend/app/services/ingest.py
import re
import uuid
import tiktoken
import structlog
import fitz  # PyMuPDF
from typing import List, Optional
from app.models.api import DocumentChunk
from app.models.enums import SourceLocation

logger = structlog.get_logger(__name__)

class IngestService:
    def __init__(self):
        self.tokenizer = tiktoken.get_encoding("cl100k_base")
        self.chunk_size = 500
        self.chunk_overlap = 100

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

        tokens = self.tokenizer.encode(text)
        chunks = []
        current_chapter = self._detect_chapter_or_scene(text[:300])
        
        if not tokens:
            return []

        for i in range(0, len(tokens), self.chunk_size - self.chunk_overlap):
            chunk_tokens = tokens[i : i + self.chunk_size]
            chunk_text = self.tokenizer.decode(chunk_tokens)
            
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
                # 2. DocumentChunk 생성 시 location에 dict를 직접 넘깁니다.
                chunk = DocumentChunk(
                    id=str(uuid.uuid4()),
                    source_id=source_id,
                    chunk_index=len(chunks),
                    content=chunk_text,
                    location=location_data  # 👈 객체 대신 dict 전달
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
        """PyMuPDF(fitz)를 사용하여 PDF에서 텍스트를 정밀 추출합니다."""
        all_chunks = []
        try:
            # 메모리에서 직접 PDF 열기
            doc = fitz.open(stream=content, filetype="pdf")
            
            for i, page in enumerate(doc):
                # 텍스트 추출 (PyPDF2보다 훨씬 강력함)
                page_text = page.get_text("text")
                
                if not page_text or len(page_text.strip()) < 5:
                    continue
                    
                page_chunks = self._create_chunks(
                    page_text, source_id, filename, start_page=i+1
                )
                all_chunks.extend(page_chunks)
            
            doc.close()
        except Exception as e:
            logger.error("PDF parsing error", error=str(e))
            
        return all_chunks