# backend/tests/test_extraction.py

import pytest

from app.services.ingest import IngestService
from app.services.mock_extraction import MockExtractionService
from app.models.enums import SourceType


@pytest.mark.asyncio
async def test_ingest_and_extract(tmp_path):

    sample_text = """
    철수는 범인을 봤다.
    그러나 영희는 철수가 범인을 봤다는 걸 모른다.
    """

    file = tmp_path / "sample.txt"

    file.write_text(sample_text, encoding="utf-8")

    ingest = IngestService()

    chunks = await ingest.parse_txt(
        str(file),
        SourceType.SCENARIO
    )

    assert len(chunks) > 0
    
    extractor = MockExtractionService()

    result = await extractor.extract_from_chunk(chunks[0])

    assert result.chunk_index == 0

    assert len(result.characters) == 2

