import pytest
from app.models.api import DocumentChunk, SourceLocation
from app.services.search import MockSearchService

def test_mock_search_service():
    service = MockSearchService()
    
    loc = SourceLocation(source_id="s1", source_name="Worldview.txt", chapter="Chapter 1", page=10, line_range=(1, 5))
    chunk1 = DocumentChunk(id="c1", source_id="s1", chunk_index=0, content="Magic exists in the forest.", location=loc)
    chunk2 = DocumentChunk(id="c2", source_id="s1", chunk_index=1, content="The king rules the kingdom.", location=loc)
    
    service.index_chunks("s1", [chunk1, chunk2])
    assert len(service.chunks) == 2
    
    # Test search context
    results = service.search_context("magic forest")
    assert len(results) == 1
    assert results[0].text == "Magic exists in the forest."
    assert results[0].source_name == "Worldview.txt"
    assert "Chapter 1" in results[0].source_location
    
    # Test get source excerpts
    excerpts = service.get_source_excerpts(["c2"])
    assert len(excerpts) == 1
    assert "king rules" in excerpts[0].text
    
    # Test remove source
    service.remove_source("s1")
    assert len(service.chunks) == 0
