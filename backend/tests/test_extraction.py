# backend/tests/test_extraction.py

import pytest

from app.services.ingest import IngestService
from app.services.mock_extraction import MockExtractionService
from app.models.enums import SourceType


@pytest.mark.asyncio
async def test_ingest_and_extract(tmp_path):

    sample_text = """
    A: 나는 범인을 봤어.
    B: 어디에서?
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

    assert len(result.characters) == 2