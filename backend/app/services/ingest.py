# backend/app/services/ingest.py

import uuid
import asyncio
from pathlib import Path
from typing import List
from fastapi import HTTPException

from app.models.api import DocumentChunk
from app.models.enums import SourceType


CHUNK_SIZE = 500


class IngestService:

    """
    Phase 1 - Ingest Layer

    File → DocumentChunk
    """

    async def parse_txt(self, file_path: str, source_type: SourceType) -> List[DocumentChunk]:

        source_id = str(uuid.uuid4())
        file_name = Path(file_path).name

        try:

            try:
                text = await asyncio.to_thread(
                    Path(file_path).read_text,
                    encoding="utf-8"
                )

            except UnicodeDecodeError:

                text = await asyncio.to_thread(
                    Path(file_path).read_text,
                    encoding="cp949"
                )

        except Exception as e:

            raise HTTPException(
                status_code=400,
                detail=f"Failed to read txt file: {str(e)}"
            )

        return self._chunk_text(text, source_id, file_name, source_type)


    async def parse_pdf(self, file_path: str, source_type: SourceType):

        from PyPDF2 import PdfReader

        source_id = str(uuid.uuid4())
        file_name = Path(file_path).name

        try:
            reader = PdfReader(file_path)

        except Exception as e:

            raise HTTPException(
                status_code=400,
                detail=f"Failed to parse PDF: {str(e)}"
            )

        chunks = []
        chunk_index = 0

        for page_index, page in enumerate(reader.pages):

            text = page.extract_text()

            if not text:
                continue

            page_chunks = self._chunk_text(
                text,
                source_id,
                file_name,
                source_type
            )

            for chunk in page_chunks:

                chunk.chunk_index = chunk_index
                chunk.location["page"] = page_index + 1

                chunks.append(chunk)

                chunk_index += 1

        return chunks


    def _chunk_text(self, text: str, source_id: str, file_name: str, source_type: SourceType):

        paragraphs = text.split("\n\n")

        chunks = []
        buffer = []
        current_length = 0
        chunk_index = 0

        for paragraph in paragraphs:

            words = paragraph.split()

            if current_length + len(words) > CHUNK_SIZE and buffer:

                content = "\n\n".join(buffer)

                chunk = DocumentChunk(
                    id=str(uuid.uuid4()),
                    source_id=source_id,
                    chunk_index=chunk_index,
                    content=content,
                    location={
                        "source_id": source_id,
                        "source_name": file_name,
                        "source_type": source_type,
                        "page": None,
                        "chapter": None,
                        "line_range": None
                    }
                )

                chunks.append(chunk)

                buffer = []
                current_length = 0
                chunk_index += 1

            buffer.append(paragraph)
            current_length += len(words)

        if buffer:

            content = "\n\n".join(buffer)

            chunk = DocumentChunk(
                id=str(uuid.uuid4()),
                source_id=source_id,
                chunk_index=chunk_index,
                content=content,
                location={
                    "source_id": source_id,
                    "source_name": file_name,
                    "source_type": source_type,
                    "page": None,
                    "chapter": None,
                    "line_range": None
                }
            )

            chunks.append(chunk)

        return chunks