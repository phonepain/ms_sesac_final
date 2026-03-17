# backend/app/services/ingest.py

import uuid
import asyncio
from pathlib import Path
from typing import List
from fastapi import HTTPException

from app.models.api import DocumentChunk
from app.models.enums import SourceType, SourceLocation


CHUNK_SIZE = 500
OVERLAP = 100


class IngestService:
    """
    Phase 1 - Ingest Layer

    역할:
    파일 → DocumentChunk

    데이터 흐름

    File Upload
        ↓
    IngestService.parse_txt / parse_pdf
        ↓
    DocumentChunk 생성
        ↓
    ExtractionService 전달
    """

    # ----------------------------------------------------------
    # TXT 파일 파싱
    # ----------------------------------------------------------
    async def parse_txt(self, file_path: str, source_type: SourceType) -> List[DocumentChunk]:

        try:
            # Step 1: UTF-8 시도
            # Step 2: 실패 시 cp949 fallback
            try:
                text = await asyncio.to_thread(
                    Path(file_path).read_text,
                    encoding="utf-8"
                )

            except UnicodeDecodeError:
                # Windows 한글 파일 대응
                text = await asyncio.to_thread(
                    Path(file_path).read_text,
                    encoding="cp949"
                )

        except Exception as e:

            raise HTTPException(
                status_code=400,
                detail=f"Failed to read txt file: {str(e)}"
            )

        return self._chunk_text(text, file_path, source_type)


    # ----------------------------------------------------------
    # PDF 파싱
    # ----------------------------------------------------------
    async def parse_pdf(self, file_path: str, source_type: SourceType):

        try:
            from PyPDF2 import PdfReader

            reader = PdfReader(file_path)

        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to parse PDF: {str(e)}"
            )

        chunks = []
        discourse = 1.0
        chunk_index = 0

        for page_index, page in enumerate(reader.pages):

            text = page.extract_text()

            if not text:
                continue

            page_chunks = self._chunk_text(
                text,
                source_id=file_path,
                source_type=source_type
            )

            for chunk in page_chunks:

                chunk.chunk_index = chunk_index
                chunk.location.page = page_index + 1

                chunks.append(chunk)

                discourse += 0.1
                chunk_index += 1

        return chunks


    # ----------------------------------------------------------
    # 텍스트 Chunking
    #
    # 500 token 단위
    # 100 token overlap
    # ----------------------------------------------------------
    def _chunk_text(self, text: str, source_id: str, source_type: SourceType):

        tokens = text.split()

        chunks = []

        start = 0
        chunk_index = 0

        while start < len(tokens):

            end = start + CHUNK_SIZE

            content = " ".join(tokens[start:end])

            chunk = DocumentChunk(
                id=str(uuid.uuid4()),
                source_id=source_id,
                chunk_index=chunk_index,
                content=content,
                location={
                    "source_id": source_id,
                    "source_name": source_id,
                    "page": None,
                    "chapter": None,
                    "line_range": None
                }
            )

            chunks.append(chunk)

            chunk_index += 1
            start += CHUNK_SIZE - OVERLAP

        return chunks