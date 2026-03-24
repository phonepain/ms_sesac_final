# backend/app/services/normalization.py
import asyncio
import json
import re
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Set

import structlog
from openai import AsyncAzureOpenAI

from app.config import settings
from app.models.intermediate import (
    ConflictDescription,
    ExtractionResult,
    NormalizationResult,
    NormalizedCharacter,
    NormalizedEvent,
    NormalizedFact,
    RawCharacter,
    RawEmotion,
    RawEvent,
    RawFact,
    RawItemEvent,
    RawKnowledgeEvent,
    RawRelationship,
    RawTrait,
    SourceConflict,
)
from app.prompts.normalize_entities import NORMALIZE_PROMPT

logger = structlog.get_logger(__name__)


class _NormalizationCore:
    _NEGATION_MARKERS = {"아니다", "아닌", "없다", "없음", "아니", "못", "않", "not", "never", "no"}
    _NEGATION_PREFIXES = ("아니", "않", "못", "없", "not")
    _TOKEN_SUFFIXES = (
        "입니다",
        "이었다",
        "였다",
        "이다",
        "다",
        "은",
        "는",
        "이",
        "가",
        "을",
        "를",
        "의",
        "와",
        "과",
    )
    _SEMANTIC_STOPWORDS = {
        "은",
        "는",
        "이",
        "가",
        "을",
        "를",
        "의",
        "에",
        "과",
        "와",
        "and",
        "or",
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
    }

    async def normalize(self, extractions: List[ExtractionResult]) -> NormalizationResult:
        """[PHASE2] Integrate extraction outputs into normalized entities."""
        logger.info("Starting Global Normalization", chunk_count=len(extractions))

        # 1. Collect raw entities by type.
        all_raw_chars: List[RawCharacter] = []
        all_raw_facts: List[RawFact] = []
        all_raw_events: List[RawEvent] = []
        all_traits: List[RawTrait] = []
        all_relationships: List[RawRelationship] = []
        all_emotions: List[RawEmotion] = []
        all_item_events: List[RawItemEvent] = []
        all_knowledge_events: List[RawKnowledgeEvent] = []
        for ext in extractions:
            all_raw_chars.extend(ext.characters)
            all_raw_facts.extend(ext.facts)
            all_raw_events.extend(ext.events)
            all_traits.extend(ext.traits)
            all_relationships.extend(ext.relationships)
            all_emotions.extend(ext.emotions)
            all_item_events.extend(ext.item_events)
            all_knowledge_events.extend(ext.knowledge_events)

        # 2. Normalize characters/facts/events in parallel.
        char_task = self._normalize_characters(all_raw_chars)
        fact_task = self._merge_facts(all_raw_facts)
        # [CHANGED][PHASE2-3] Include RawEvent so Phase 3 can materialize Event vertices.
        event_task = self._normalize_events(all_raw_events)

        normalized_chars, normalized_facts, normalized_events = await asyncio.gather(
            char_task, fact_task, event_task
        )

        normalized = NormalizationResult(
            characters=normalized_chars,
            facts=normalized_facts,
            events=normalized_events,
            traits=all_traits,
            relationships=all_relationships,
            emotions=all_emotions,
            item_events=all_item_events,
            knowledge_events=all_knowledge_events,
            source_conflicts=[],
        )
        normalized.source_conflicts = self._detect_source_conflicts(normalized)
        return normalized

    async def _normalize_characters(self, raws: List[RawCharacter]) -> List[NormalizedCharacter]:
        raise NotImplementedError

    async def _normalize_facts(self, raws: List[RawFact]) -> List[NormalizedFact]:
        # [CHANGED][PHASE2-3] Backward compatibility: 기존 내부 호출 경로 유지.
        return await self._merge_facts(raws)

    async def _merge_facts(self, raws: List[RawFact]) -> List[NormalizedFact]:
        """[CHANGED][PHASE2-3] 의미 유사도 기반 Fact 병합 (완전 일치 + 경량 의미 유사도)."""
        if not raws:
            return []

        merged_facts: List[NormalizedFact] = []
        for r in raws:
            merge_idx = self._find_merge_candidate(r, merged_facts)
            if merge_idx is None:
                merged_facts.append(
                    NormalizedFact(
                    content=r.content,
                    category=r.category_hint or "world_fact",
                    merged_from=[r],
                    )
                )
                continue

            target = merged_facts[merge_idx]
            target.merged_from.append(r)
            if target.category == "world_fact" and r.category_hint:
                target.category = r.category_hint

        return merged_facts

    async def _normalize_events(self, raws: List[RawEvent]) -> List[NormalizedEvent]:
        """[CHANGED][PHASE2-3] Convert RawEvent list into Event materialization inputs."""
        if not raws:
            return []

        event_map: Dict[str, NormalizedEvent] = {}
        for r in raws:
            description = r.description.strip()
            location = (r.location_hint or "").strip() or None
            key = f"{description}::{location or ''}"

            if key not in event_map:
                event_map[key] = NormalizedEvent(
                    description=description,
                    event_type=r.event_type or "scene",
                    location=location,
                    characters_involved=list(r.characters_involved),
                    merged_from=[r],
                    status_char=r.status_char,
                )
                continue

            merged = event_map[key]
            existing = set(merged.characters_involved)
            for name in r.characters_involved:
                if name not in existing:
                    merged.characters_involved.append(name)
                    existing.add(name)
            merged.merged_from.append(r)

        return list(event_map.values())

    def _find_merge_candidate(
        self,
        raw_fact: RawFact,
        merged_facts: List[NormalizedFact],
    ) -> Optional[int]:
        for idx, existing in enumerate(merged_facts):
            if self._is_semantically_same_fact(raw_fact.content, existing.content):
                return idx
        return None

    def _is_semantically_same_fact(self, left: str, right: str) -> bool:
        left_norm = self._normalize_text(left)
        right_norm = self._normalize_text(right)
        if left_norm == right_norm:
            return True

        # [CHANGED][PHASE2-3] 의미 유사도 병합 시 부정/수치 충돌은 병합 금지.
        if self._is_conflicting_polarity(left, right) or self._is_numeric_conflict(left, right):
            return False

        ratio = SequenceMatcher(None, left_norm, right_norm).ratio()
        if ratio >= 0.90:
            return True

        left_tokens = self._semantic_tokens(left)
        right_tokens = self._semantic_tokens(right)
        return self._jaccard(left_tokens, right_tokens) >= 0.78

    def _is_conflicting_polarity(self, left: str, right: str) -> bool:
        left_neg = self._contains_negation(left)
        right_neg = self._contains_negation(right)
        if left_neg == right_neg:
            return False

        left_core = self._semantic_tokens(left, strip_negation=True)
        right_core = self._semantic_tokens(right, strip_negation=True)
        core_similarity = self._jaccard(left_core, right_core)
        return core_similarity >= 0.60

    def _is_numeric_conflict(self, left: str, right: str) -> bool:
        left_nums = set(re.findall(r"\d+", left))
        right_nums = set(re.findall(r"\d+", right))
        if not left_nums or not right_nums:
            return False
        if left_nums == right_nums:
            return False

        left_tokens = {t for t in self._semantic_tokens(left) if not re.search(r"\d", t)}
        right_tokens = {t for t in self._semantic_tokens(right) if not re.search(r"\d", t)}
        return self._jaccard(left_tokens, right_tokens) >= 0.60

    def _contains_negation(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        tokens = normalized.split()
        for token in tokens:
            if token in self._NEGATION_MARKERS:
                return True
            if any(token.startswith(prefix) for prefix in self._NEGATION_PREFIXES):
                return True
        return False

    def _normalize_text(self, text: str) -> str:
        lowered = text.strip().lower()
        lowered = re.sub(r"[^\w가-힣\s]", " ", lowered)
        return re.sub(r"\s+", " ", lowered).strip()

    def _semantic_tokens(self, text: str, strip_negation: bool = False) -> Set[str]:
        raw_tokens = re.findall(r"[가-힣A-Za-z0-9]+", self._normalize_text(text))
        tokens = {self._normalize_token(token) for token in raw_tokens}
        tokens = {token for token in tokens if token and token not in self._SEMANTIC_STOPWORDS}
        if strip_negation:
            tokens = {token for token in tokens if token not in self._NEGATION_MARKERS}
        return tokens

    def _normalize_token(self, token: str) -> str:
        normalized = token.strip().lower()
        for suffix in self._TOKEN_SUFFIXES:
            if normalized.endswith(suffix) and len(normalized) > len(suffix) + 1:
                normalized = normalized[: -len(suffix)]
                break
        return normalized

    def _jaccard(self, left: Set[str], right: Set[str]) -> float:
        if not left or not right:
            return 0.0
        return len(left & right) / len(left | right)

    def _detect_source_conflicts(self, normalized: NormalizationResult) -> List[SourceConflict]:
        """[CHANGED][PHASE2-3] source_chunk_id 기반 다중 소스 충돌 감지."""
        fact_conflicts: Dict[str, Dict[str, object]] = {}
        facts = normalized.facts

        for i in range(len(facts)):
            for j in range(i + 1, len(facts)):
                left = facts[i]
                right = facts[j]
                if not self._facts_from_different_sources(left, right):
                    continue
                if not self._are_fact_values_conflicting(left.content, right.content):
                    continue

                key = self._build_conflict_key(left.content, right.content)
                bucket = fact_conflicts.setdefault(
                    key,
                    {"values": set(), "descriptions": {}},
                )
                bucket["values"].update({left.content, right.content})

                descriptions: Dict[str, str] = bucket["descriptions"]  # type: ignore[assignment]
                self._append_fact_descriptions(descriptions, left)
                self._append_fact_descriptions(descriptions, right)

        conflicts: List[SourceConflict] = []
        for key, payload in fact_conflicts.items():
            descriptions = [
                ConflictDescription(source_id=source_id, text=text)
                for source_id, text in sorted(payload["descriptions"].items())
            ]
            conflicting_values = sorted(payload["values"])
            if len(conflicting_values) < 2:
                continue
            conflicts.append(
                SourceConflict(
                    # [CHANGED][PHASE2-3] 어떤 fact 그룹의 충돌인지 식별 가능하도록 key 포함.
                    entity_type=f"fact:{key}",
                    descriptions=descriptions,
                    conflicting_values=conflicting_values,
                )
            )

        return conflicts

    def _facts_from_different_sources(self, left: NormalizedFact, right: NormalizedFact) -> bool:
        left_sources = {rf.source_chunk_id for rf in left.merged_from if rf.source_chunk_id}
        right_sources = {rf.source_chunk_id for rf in right.merged_from if rf.source_chunk_id}
        if not left_sources or not right_sources:
            return False
        return bool(left_sources - right_sources or right_sources - left_sources)

    def _are_fact_values_conflicting(self, left: str, right: str) -> bool:
        if self._normalize_text(left) == self._normalize_text(right):
            return False
        return self._is_conflicting_polarity(left, right) or self._is_numeric_conflict(left, right)

    def _build_conflict_key(self, left: str, right: str) -> str:
        left_core = self._semantic_tokens(left, strip_negation=True)
        right_core = self._semantic_tokens(right, strip_negation=True)
        core = sorted(left_core & right_core)
        if not core:
            core = sorted((left_core | right_core))
        return "_".join(core[:4]) if core else "general"

    def _append_fact_descriptions(self, sink: Dict[str, str], fact: NormalizedFact) -> None:
        for raw in fact.merged_from:
            source_id = raw.source_chunk_id or "unknown"
            sink[source_id] = fact.content


class MockNormalizationService(_NormalizationCore):
    """[CHANGED][PHASE2-3] 별도 Mock 서비스 클래스 분리 (기존 use_mock 동작 분리)."""

    async def _normalize_characters(self, raws: List[RawCharacter]) -> List[NormalizedCharacter]:
        if not raws:
            return []

        grouped: Dict[str, List[RawCharacter]] = defaultdict(list)
        for r in raws:
            key = r.name.replace(" ", "").lower()
            grouped[key].append(r)

        result: List[NormalizedCharacter] = []
        for items in grouped.values():
            canonical = items[0].name
            aliases = sorted({x.name for x in items if x.name != canonical})
            result.append(
                NormalizedCharacter(
                    canonical_name=canonical,
                    all_aliases=aliases,
                    tier=4,
                    description=items[0].role_hint,
                    merged_from=items,
                )
            )
        return result


class NormalizationService(_NormalizationCore):
    def __init__(self):
        self._mock_service: Optional[MockNormalizationService] = None
        # [CHANGED][PHASE0-3][CONFIG-COMPAT] Config field names aligned to original config.py (AZURE_OPENAI_*).
        if not (settings.AZURE_OPENAI_ENDPOINT and settings.AZURE_OPENAI_API_KEY):
            # [CHANGED][PHASE2-3] 내부 분기 대신 MockNormalizationService 인스턴스로 위임.
            self._mock_service = MockNormalizationService()
            return

        self.client = AsyncAzureOpenAI(
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_key=settings.AZURE_OPENAI_API_KEY,
            api_version=settings.AZURE_OPENAI_API_VERSION,
        )
        self.deployment_name = settings.AZURE_OPENAI_NORMALIZATION_DEPLOYMENT

    @property
    def use_mock(self) -> bool:
        return self._mock_service is not None

    async def normalize(self, extractions: List[ExtractionResult]) -> NormalizationResult:
        if self._mock_service is not None:
            return await self._mock_service.normalize(extractions)
        return await super().normalize(extractions)

    async def _normalize_characters(self, raws: List[RawCharacter]) -> List[NormalizedCharacter]:
        """수만 개의 캐릭터 파편을 지능적으로 통합합니다."""
        if not raws:
            return []

        # [대용량 최적화] 동일한 이름은 사전 병합하여 LLM에 보낼 토큰을 줄입니다.
        unique_names_map = {}
        for r in raws:
            if r.name not in unique_names_map:
                unique_names_map[r.name] = r.role_hint

        # LLM에게는 중복 없는 이름 리스트만 보냅니다.
        logger.info("Simplifying characters for LLM", unique_count=len(unique_names_map))
        prompt = NORMALIZE_PROMPT.format(json_data=json.dumps(unique_names_map, ensure_ascii=False))

        try:
            response = await self.client.beta.chat.completions.parse(
                model=self.deployment_name,
                messages=[
                    {"role": "system", "content": "당신은 데이터 정규화 전문가입니다. 동일 인물을 찾아 그룹화하세요."},
                    {"role": "user", "content": prompt},
                ],
                response_format=NormalizationResult,  # 캐릭터 리스트 스키마 활용
            )

            result: NormalizationResult = response.choices[0].message.parsed

            # 3. 통합된 결과에 원본 Raw 데이터(merged_from)를 다시 매핑 (계보 추적)
            for nc in result.characters:
                # canonical_name이나 aliases에 포함된 모든 Raw 데이터를 찾음
                nc.merged_from = [
                    r for r in raws
                    if r.name == nc.canonical_name or r.name in nc.all_aliases
                ]

            return result.characters

        except Exception as e:
            logger.error("Character normalization failed", error=str(e))
            return []
