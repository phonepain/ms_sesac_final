from pathlib import Path

import pytest

from app.models.enums import SourceType
from app.models.vertices import Source
from app.services.extraction import ExtractionService
from app.services.graph import InMemoryGraphService
from app.services.ingest import IngestService
from app.services.normalization import NormalizationService


@pytest.mark.asyncio
async def test_phase03_pipeline_with_team_pdf():
    # [CHANGED][PHASE0-3] 팀 제공 샘플 PDF로 0~3단계 파이프라인이 끊기지 않는지 검증
    repo_root = Path(__file__).resolve().parents[2]
    pdf_path = repo_root / "data" / "sample" / "HP_Stone_txt.pdf"
    assert pdf_path.exists(), f"Missing test file: {pdf_path}"

    ingest = IngestService()
    chunks = await ingest.process_file(pdf_path.read_bytes(), pdf_path.name, "phase03-source")
    assert len(chunks) > 0

    extractor = ExtractionService()
    # 테스트 시간을 제어하기 위해 앞쪽 청크만 샘플링해 Phase 0~3 동작 여부를 확인
    chunk_subset = chunks[:20]
    extractions = await extractor.extract_from_chunks(chunk_subset, "scenario")
    assert len(extractions) == len(chunk_subset)

    total_characters = sum(len(result.characters) for result in extractions)
    total_facts = sum(len(result.facts) for result in extractions)
    total_events = sum(len(result.events) for result in extractions)

    # [CHANGED][PHASE0-3] 기존 공백 추출 문제 재발 방지: 최소 사실/이벤트는 반드시 있어야 함
    assert total_facts > 0
    assert total_events > 0
    assert total_characters > 0

    normalizer = NormalizationService()
    normalized = await normalizer.normalize(extractions)

    graph = InMemoryGraphService()
    source = Source(
        source_id="phase03-source",
        source_type=SourceType.SCENARIO,
        name=pdf_path.name,
        metadata="{}",
    )
    created = graph.materialize(normalized, source)

    # [CHANGED][PHASE0-3] Materialization 결과 최소 검증
    assert len(created["source"]) == 1
    assert len(created["facts"]) > 0

    stats = graph.get_stats()
    assert stats.sources == 1
    assert stats.facts > 0
