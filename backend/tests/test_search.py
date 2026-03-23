import pytest
from app.models.api import DocumentChunk, ChunkLocation
from app.services.search import MockSearchService


@pytest.fixture
def service():
    return MockSearchService()


@pytest.fixture
def sample_chunks():
    loc = ChunkLocation(source_id="s1", source_name="Worldview.txt", chapter="Chapter 1", page=10, line_range=(1, 5))
    return [
        DocumentChunk(id="c1", source_id="s1", chunk_index=0, content="Magic exists in the forest.", location=loc),
        DocumentChunk(id="c2", source_id="s1", chunk_index=1, content="The king rules the kingdom.", location=loc),
    ]


async def test_index_and_search(service, sample_chunks):
    await service.index_chunks("s1", sample_chunks)
    assert len(service.chunks) == 2

    results = await service.search_context("magic forest")
    assert len(results) == 1
    assert results[0].text == "Magic exists in the forest."
    assert results[0].source_name == "Worldview.txt"
    assert "Chapter 1" in results[0].source_location


async def test_get_source_excerpts(service, sample_chunks):
    await service.index_chunks("s1", sample_chunks)
    excerpts = await service.get_source_excerpts(["c2"])
    assert len(excerpts) == 1
    assert "king rules" in excerpts[0].text


async def test_remove_source(service, sample_chunks):
    await service.index_chunks("s1", sample_chunks)
    await service.remove_source("s1")
    assert len(service.chunks) == 0


async def test_search_no_match(service, sample_chunks):
    await service.index_chunks("s1", sample_chunks)
    results = await service.search_context("이 단어는 없음 xyz")
    assert results == []
