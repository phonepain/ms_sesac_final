import pytest

from app.models.intermediate import ExtractionResult, RawFact
from app.services.normalization import MockNormalizationService, NormalizationService


@pytest.mark.asyncio
async def test_merge_facts_uses_semantic_similarity_and_keeps_conflicts_separate():
    service = MockNormalizationService()
    normalized = await service.normalize(
        [
            ExtractionResult(
                facts=[
                    RawFact(content="John is 20 years old", source_chunk_id="src-a"),
                    RawFact(content="John is 20 years-old.", source_chunk_id="src-b"),
                    RawFact(content="John is 25 years old", source_chunk_id="src-c"),
                    RawFact(content="John is not a wizard", source_chunk_id="src-a"),
                    RawFact(content="John is a wizard", source_chunk_id="src-b"),
                ]
            )
        ]
    )

    # [CHANGED][PHASE2-3] Near-duplicate age facts are merged, but contradiction pairs stay split.
    assert len(normalized.facts) == 4

    age_20 = next((f for f in normalized.facts if f.content == "John is 20 years old"), None)
    assert age_20 is not None
    assert sorted(m.source_chunk_id for m in age_20.merged_from) == ["src-a", "src-b"]


@pytest.mark.asyncio
async def test_detect_source_conflicts_returns_conflicts_for_numeric_and_negation_mismatch():
    service = MockNormalizationService()
    normalized = await service.normalize(
        [
            ExtractionResult(
                facts=[
                    RawFact(content="John is 20 years old", source_chunk_id="src-a"),
                    RawFact(content="John is 25 years old", source_chunk_id="src-b"),
                    RawFact(content="John is not a wizard", source_chunk_id="src-c"),
                    RawFact(content="John is a wizard", source_chunk_id="src-d"),
                ]
            )
        ]
    )

    assert len(normalized.source_conflicts) == 2

    conflict_values = {tuple(sorted(c.conflicting_values)) for c in normalized.source_conflicts}
    assert ("John is 20 years old", "John is 25 years old") in conflict_values
    assert ("John is a wizard", "John is not a wizard") in conflict_values


@pytest.mark.asyncio
async def test_normalization_service_uses_mock_service_when_azure_settings_missing(monkeypatch):
    monkeypatch.setattr("app.services.normalization.settings.AZURE_OPENAI_ENDPOINT", "")
    monkeypatch.setattr("app.services.normalization.settings.AZURE_OPENAI_API_KEY", "")

    service = NormalizationService()
    assert service._mock_service is not None

    normalized = await service.normalize(
        [ExtractionResult(facts=[RawFact(content="A fact", source_chunk_id="s1")])]
    )
    assert len(normalized.facts) == 1
