import asyncio
import json
import time
import uuid
import structlog
from typing import Dict, Any, Optional, Tuple, Literal, List
from openai import AsyncAzureOpenAI

from app.config import settings
from app.models.intermediate import ContradictionVerification
from app.models.api import (
    ManuscriptInput, AnalysisResponse, ContradictionReport, EvidenceItem
)
from app.models.enums import (
    ContradictionType, Severity, ConfirmationType, ConfirmationStatus
)
from app.models.vertices import UserConfirmation, SourceExcerpt
from app.prompts.verify_contradiction import CONTRADICTION_PROMPT
from app.prompts.world_rule_check import WORLD_RULE_CHECK_PROMPT

# ConfirmationType → ContradictionType 매핑
_CONFIRMATION_TO_CONTRADICTION: Dict[ConfirmationType, ContradictionType] = {
    ConfirmationType.FLASHBACK_CHECK: ContradictionType.TIMELINE,
    ConfirmationType.TIMELINE_AMBIGUITY: ContradictionType.TIMELINE,
    ConfirmationType.RELATIONSHIP_AMBIGUITY: ContradictionType.RELATIONSHIP,
    ConfirmationType.EMOTION_SHIFT: ContradictionType.EMOTION,
    ConfirmationType.ITEM_DISCREPANCY: ContradictionType.ITEM,
    ConfirmationType.INTENTIONAL_CHANGE: ContradictionType.TRAIT,
    ConfirmationType.SOURCE_CONFLICT: ContradictionType.ASYMMETRY,
    ConfirmationType.FORESHADOWING: ContradictionType.ASYMMETRY,
    ConfirmationType.UNRELIABLE_NARRATOR: ContradictionType.DECEPTION,
}

logger = structlog.get_logger()


class DetectionService:
    def __init__(self):
        self._mock_mode = not (
            settings.AZURE_OPENAI_ENDPOINT and settings.AZURE_OPENAI_API_KEY
        )
        if self._mock_mode:
            logger.warning("DetectionService: API 키/엔드포인트 없음 → mock 모드로 동작 (soft violation은 confidence=0.5로 처리)")
            self.client = None
            self.deployment_name = None
            return

        self.client = AsyncAzureOpenAI(
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_key=settings.AZURE_OPENAI_API_KEY,
            api_version=settings.AZURE_OPENAI_API_VERSION,
        )
        self.deployment_name = settings.AZURE_OPENAI_DETECTION_DEPLOYMENT

    # ── Hard / Soft 분류 ──────────────────────────────────────

    def _classify_hard_soft(self, violation: Dict[str, Any]) -> Literal["hard", "soft"]:
        """is_hard 플래그(graph.py _make_violation에서 설정) 기반 분류.

        Hard 조건 (is_hard=True):
        - confidence >= 0.8 AND needs_user_input = False
        """
        return "hard" if violation.get("is_hard") else "soft"

    # ── Soft LLM 검증 ─────────────────────────────────────────

    async def _verify_soft_with_llm(
        self, violation: Dict[str, Any]
    ) -> Tuple[float, str]:
        """Soft 후보만 LLM으로 정밀 검증.

        Returns:
            (confidence, reasoning)
        """
        if self._mock_mode:
            return 0.5, "LLM 검증 비활성화 (API 키 없음) — 사용자 확인 필요"

        prompt = CONTRADICTION_PROMPT.format(violation_data=str(violation))
        try:
            response = await self.client.beta.chat.completions.parse(
                model=self.deployment_name,
                messages=[
                    {"role": "system", "content": "당신은 서사 정합성 및 논리 구조 분석 전문가입니다."},
                    {"role": "user", "content": prompt},
                ],
                response_format=ContradictionVerification,
            )
            result = response.choices[0].message.parsed
            if response.usage:
                from app.services.cost_tracker import get_tracker
                get_tracker().add(self.deployment_name, response.usage)
            logger.info(
                "soft_llm_verify",
                confidence=result.confidence,
                is_contradiction=result.is_contradiction,
            )
            return result.confidence, result.reasoning
        except Exception as e:
            logger.error("soft_llm_verify_failed", error=str(e))
            return 0.0, f"검증 오류: {str(e)}"

    # ── 유틸리티 ─────────────────────────────────────────────

    @staticmethod
    def _common_substr_len(a: str, b: str) -> int:
        """두 문자열의 최장 공통 부분문자열 길이."""
        if not a or not b:
            return 0
        short, long_ = (a, b) if len(a) <= len(b) else (b, a)
        for length in range(len(short), 9, -1):
            for start in range(len(short) - length + 1):
                if short[start:start + length] in long_:
                    return length
        return 0

    @staticmethod
    def _extract_keywords(text: str) -> set:
        """한글 텍스트에서 조사/어미를 제거한 핵심 키워드 추출."""
        import re as _re
        # 숫자+단위
        nums = set(_re.findall(r'\d+[분시간일월년]', text))
        # 한글 단어에서 흔한 조사/어미 strip
        words = _re.findall(r'[가-힣]+', text)
        cleaned = set()
        for w in words:
            w = _re.sub(
                r'(에서|까지는|까지|으로는|에서의|이라|으로|에게|한테'
                r'|하며|하는데|했다고|되어|있어|가능|통해서만|통해|걸려야'
                r'|만에|하는|인데|있는|했다|된다|한다|이다|하여|대로'
                r'|이지만|라는|라고|에는|으며|이며|에도|지만|이나)$', '', w)
            w = _re.sub(r'(을|를|이|가|은|는|의|에|로|과|와|도|서|만|씩|들|째)$', '', w)
            if len(w) >= 2:
                cleaned.add(w)
        return cleaned | nums

    # ── violation dict → Pydantic 변환 ────────────────────────

    @staticmethod
    def _fmt_evidence(e: Dict[str, Any]) -> str:
        """evidence dict를 사람이 읽기 좋은 문자열로 변환."""
        parts = []
        if "story_order" in e:
            parts.append(f"story_order={e['story_order']}")
        if "owners" in e and isinstance(e["owners"], list):
            parts.append(f"동시 소유자 {len(e['owners'])}명")
        if "character_name" in e:
            parts.append(f"캐릭터: {e['character_name']}")
        if "fact_content" in e:
            parts.append(f"사실: {str(e['fact_content'])[:60]}")
        if "relationship_types" in e:
            parts.append(f"관계: {e['relationship_types']}")
        if "values" in e and isinstance(e["values"], list):
            parts.append(f"값: {e['values']}")
        if "knower" in e:
            parts.append(f"인지자: {e['knower']}")
        if "fact" in e:
            parts.append(f"사실: {str(e['fact'])[:60]}")
        if not parts:
            for k, v_val in e.items():
                if not k.endswith("_id") and k not in ("type", "is_hard"):
                    parts.append(f"{k}: {v_val}")
        return " | ".join(parts) if parts else "(정보 없음)"

    def _to_report(self, v: Dict[str, Any]) -> ContradictionReport:
        evidence = [
            EvidenceItem(
                source_name=str(e.get("type", "그래프")),
                source_location=str(e.get("story_order", "")),
                text=self._fmt_evidence(e),
            )
            for e in v.get("evidence", [])
        ]
        # original_text 폴백 체인: original_text → dialogue → evidence 첫 항목 텍스트 → description
        original_text = v.get("original_text") or v.get("dialogue") or ""
        if not original_text and evidence:
            original_text = evidence[0].text or ""
        if not original_text:
            original_text = v.get("description") or ""

        return ContradictionReport(
            id=v.get("id", ""),
            type=v.get("type", ContradictionType.ASYMMETRY),
            severity=v.get("severity", Severity.MAJOR),
            hard_or_soft="hard" if v.get("is_hard") else "soft",
            character_id=v.get("character_id"),
            character_name=v.get("character_name"),
            dialogue=v.get("dialogue"),
            description=v.get("description", ""),
            evidence=evidence,
            confidence=v.get("confidence", 0.0),
            suggestion=v.get("suggestion"),
            alternative=v.get("alternative_interpretation"),
            needs_user_input=v.get("needs_user_input", False),
            user_question=v.get("user_question"),
            original_text=original_text,
            chunk_id=v.get("chunk_id"),
        )

    def _to_confirmation(self, v: Dict[str, Any]) -> UserConfirmation:
        return UserConfirmation(
            source_id="detection",
            confirmation_type=(
                v.get("confirmation_type") or ConfirmationType.TIMELINE_AMBIGUITY
            ),
            status=ConfirmationStatus.PENDING,
            question=v.get("user_question") or v.get("description", ""),
            context_summary=v.get("description", ""),
            source_excerpts=[],
            related_entity_ids=(
                [v["character_id"]] if v.get("character_id") else []
            ),
        )

    # ── 핵심 처리 ─────────────────────────────────────────────

    async def process_violations(
        self, violations: Dict[str, List]
    ) -> Tuple[List[ContradictionReport], List[UserConfirmation]]:
        """find_all_violations() 결과 처리.

        - Hard → 자동 ContradictionReport
        - Soft → LLM 검증 → confidence≥0.8이면 Report, 아니면 UserConfirmation
        """
        reports: List[ContradictionReport] = []
        confirmations: List[UserConfirmation] = []

        # Hard: 자동 판정
        for v in violations.get("hard", []):
            reports.append(self._to_report(v))
            logger.info("hard_auto_report", violation_type=str(v.get("type")))

        # Soft: LLM 검증 (병렬)
        soft_list = violations.get("soft", [])
        if soft_list:
            soft_results = await asyncio.gather(
                *[self._verify_soft_with_llm(v) for v in soft_list]
            )
            for v, (confidence, reasoning) in zip(soft_list, soft_results):
                if confidence >= 0.8:
                    v["confidence"] = confidence
                    reports.append(self._to_report(v))
                    logger.info("soft_auto_report", confidence=confidence)
                else:
                    if not v.get("user_question"):
                        v["user_question"] = reasoning
                    confirmations.append(self._to_confirmation(v))
                    logger.info("soft_needs_confirmation", confidence=confidence)

        return reports, confirmations

    # ── 세계 규칙 LLM 탐지 ────────────────────────────────────

    MAX_CHARS_PER_BATCH = 15000  # 한국어 ~30K 토큰

    async def _check_world_rules_with_llm(
        self, graph_service
    ) -> List[Dict[str, Any]]:
        """그래프의 fact + event를 LLM에 보내 세계 규칙 위반을 탐지."""
        from app.services.graph import _prop

        all_facts = graph_service._vertices_by_label("fact")
        all_events = graph_service._vertices_by_label("event")

        if not all_facts or not all_events:
            return []

        # fact/event 텍스트 + 메타 수집
        fact_entries = []
        for fv in all_facts:
            content = str(_prop(fv, "content") or "")
            if content:
                fact_entries.append({
                    "content": content,
                    "id": _prop(fv, "id"),
                })

        event_entries = []
        for ev in all_events:
            desc = str(_prop(ev, "description") or "")
            if desc:
                event_entries.append({
                    "description": desc,
                    "id": _prop(ev, "id"),
                    "story_order": _prop(ev, "story_order") or _prop(ev, "discourse_order") or 0,
                })

        if not fact_entries or not event_entries:
            return []

        # 배치 분할
        event_text = "\n".join(
            f"[{i}] {e['description']}" for i, e in enumerate(event_entries)
        )
        total_event_chars = len(event_text)

        batches = []
        batch_facts = []
        batch_chars = 0
        for fe in fact_entries:
            batch_facts.append(fe)
            batch_chars += len(fe["content"])
            if batch_chars + total_event_chars > self.MAX_CHARS_PER_BATCH:
                batches.append(batch_facts)
                batch_facts = []
                batch_chars = 0
        if batch_facts:
            batches.append(batch_facts)

        if not batches:
            return []

        logger.info(
            "world_rule_llm_check",
            total_facts=len(fact_entries),
            total_events=len(event_entries),
            batches=len(batches),
        )

        # LLM 호출 (배치별 병렬)
        tasks = [
            self._call_world_rule_llm(bf, event_entries, event_text)
            for bf in batches
        ]
        batch_results = await asyncio.gather(*tasks)

        # 결과 병합 + LLM 내부 중복 제거
        raw_violations = []
        for result in batch_results:
            raw_violations.extend(result)

        # LLM이 같은 규칙-이벤트 조합을 다른 표현으로 중복 출력하는 경우 제거
        violations: List[Dict[str, Any]] = []
        seen_rule_event: set = set()       # (rule_text[:50], event_text[:50])
        seen_desc_parts: List[set] = []    # description 한글 토큰 Jaccard dedup

        for v in raw_violations:
            ev_list = v.get("evidence") or []
            rule_t = ""
            event_t = ""
            for ev_item in ev_list:
                if isinstance(ev_item, dict):
                    rule_t = str(ev_item.get("rule", ""))[:50]
                    event_t = str(ev_item.get("event", ""))[:50]

            # (rule, event) 쌍 기반 exact dedup
            if rule_t and event_t:
                re_key = (rule_t, event_t)
                if re_key in seen_rule_event:
                    logger.debug("world_rule_internal_dedup_exact", desc=v.get("description", "")[:60])
                    continue
                seen_rule_event.add(re_key)

            # description 한글 토큰 Jaccard dedup (0.5 이상 → 중복)
            desc = v.get("description", "")
            import re as _re
            parts = set(_re.findall(r'[가-힣]{2,}', desc))
            is_dup = False
            for prev in seen_desc_parts:
                union = parts | prev
                inter = parts & prev
                if union and len(inter) / len(union) > 0.5:
                    is_dup = True
                    break
            if is_dup:
                logger.debug("world_rule_internal_dedup_jaccard", desc=desc[:60])
                continue
            seen_desc_parts.append(parts)

            violations.append(v)

        logger.info("world_rule_dedup", raw=len(raw_violations), deduped=len(violations))
        return violations

    async def _call_world_rule_llm(
        self,
        fact_batch: List[Dict],
        event_entries: List[Dict],
        event_text: str,
    ) -> List[Dict[str, Any]]:
        """단일 배치에 대한 세계 규칙 LLM 호출."""
        from app.services.graph import _make_violation

        fact_text = "\n".join(
            f"[{i}] {f['content']}" for i, f in enumerate(fact_batch)
        )

        prompt = WORLD_RULE_CHECK_PROMPT.format(
            facts=fact_text,
            events=event_text,
        )

        if self._mock_mode:
            logger.info("world_rule_llm_mock — skipping")
            return []

        try:
            response = await self.client.chat.completions.create(
                model=self.deployment_name,
                messages=[
                    {"role": "system", "content": "당신은 서사 작품의 세계관 규칙 위반 전문 분석가입니다. 반드시 JSON 배열만 반환하세요."},
                    {"role": "user", "content": prompt},
                ],
                temperature=1,
            )
            raw_content = response.choices[0].message.content.strip()
            if response.usage:
                from app.services.cost_tracker import get_tracker
                get_tracker().add(self.deployment_name, response.usage)

            # JSON 파싱 (```json ... ``` 래핑 처리)
            if raw_content.startswith("```"):
                raw_content = raw_content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            items = json.loads(raw_content)
            if not isinstance(items, list):
                return []

            violations = []
            for item in items:
                rule_idx = item.get("rule_index", -1)
                event_idx = item.get("event_index", -1)
                if rule_idx < 0 or event_idx < 0:
                    continue
                if rule_idx >= len(fact_batch) or event_idx >= len(event_entries):
                    continue

                confidence = float(item.get("confidence", 0.5))
                sev_str = item.get("severity", "major")
                severity = {
                    "critical": Severity.CRITICAL,
                    "major": Severity.MAJOR,
                    "minor": Severity.MINOR,
                }.get(sev_str, Severity.MAJOR)

                # CRITICAL + high confidence → Hard 승격 (수학적/물리적 규칙 위반)
                if severity == Severity.CRITICAL:
                    needs_user = confidence < 0.85
                elif severity == Severity.MINOR:
                    needs_user = True
                else:
                    needs_user = confidence < 0.8

                violations.append(_make_violation(
                    vtype=ContradictionType.TIMELINE,
                    severity=severity,
                    description=item.get("description", "세계 규칙 위반"),
                    confidence=confidence,
                    evidence=[{
                        "rule": fact_batch[rule_idx]["content"],
                        "event": event_entries[event_idx]["description"][:100],
                        "story_order": event_entries[event_idx].get("story_order", 0),
                    }],
                    needs_user_input=needs_user,
                    confirmation_type=ConfirmationType.TIMELINE_AMBIGUITY if needs_user else None,
                    suggestion="세계 규칙과 이벤트 행동의 모순 여부를 확인하세요.",
                ))

            logger.info("world_rule_llm_result", violations=len(violations))
            return violations

        except Exception as e:
            logger.error("world_rule_llm_failed", error=str(e))
            return []

    # ── analyze / full_scan ─────────────────────────────────

    async def analyze(
        self,
        violations: Dict[str, List],
        processing_start_ms: Optional[int] = None,
        graph_service=None,
    ) -> AnalysisResponse:
        """violations dict → AnalysisResponse.

        agent.py에서 스냅샷 격리 후 find_all_violations() 결과를 여기로 전달.
        graph_service가 있으면 세계 규칙 LLM 탐지도 실행.
        """
        start = processing_start_ms or int(time.time() * 1000)

        # 세계 규칙 LLM 탐지 + process_violations 병렬 실행
        async def _empty():
            return []

        world_rule_task = (
            self._check_world_rules_with_llm(graph_service)
            if graph_service else _empty()
        )
        process_task = self.process_violations(violations)

        world_violations, (reports, confirmations) = await asyncio.gather(
            world_rule_task, process_task
        )

        # 세계 규칙 LLM 결과 cross-dedup: graph 탐지 결과와 동일 규칙/이벤트 중복 제거
        # 기존 report/confirmation에서 evidence fact 텍스트 수집
        existing_fact_keys: set = set()
        for r in reports:
            for e in r.evidence:
                if e.text:
                    for part in e.text.split(" | "):
                        if part.startswith("사실: "):
                            existing_fact_keys.add(part[4:].strip()[:60])
        for c in confirmations:
            if c.context_summary:
                existing_fact_keys.add(c.context_summary[:60])

        # 기존 description 키워드 수집 (Jaccard dedup 보조)
        existing_desc_parts: List[set] = []
        for r in reports:
            existing_desc_parts.append(self._extract_keywords(r.description))
        for c in confirmations:
            existing_desc_parts.append(self._extract_keywords(c.question or c.context_summary))

        for v in world_violations:
            is_dup = False

            # 1) evidence rule↔fact 부분문자열 매칭
            for ev_item in v.get("evidence", []):
                if isinstance(ev_item, dict):
                    rule_text = str(ev_item.get("rule", ""))
                    if rule_text and len(rule_text) > 10:
                        rule_short = rule_text[:60]
                        for existing in existing_fact_keys:
                            shorter = min(rule_short, existing, key=len)
                            longer = max(rule_short, existing, key=len)
                            if shorter in longer or self._common_substr_len(shorter, longer) >= 20:
                                is_dup = True
                                break
                    if is_dup:
                        break
            if is_dup:
                logger.debug("world_rule_cross_dedup_fact", desc=v.get("description", "")[:60])
                continue

            # 2) description 키워드 Jaccard 보조 (Hard 우선)
            desc = v.get("description", "")
            v_kw = self._extract_keywords(desc)
            dup_conf_idx = -1
            if v_kw and len(v_kw) >= 3:
                # reports와 비교
                for prev in existing_desc_parts[:len(reports)]:
                    if not prev:
                        continue
                    union = v_kw | prev
                    inter = v_kw & prev
                    if not union:
                        continue
                    jac = len(inter) / len(union)
                    if jac > 0.5 or (jac > 0.3 and len(inter) >= 3):
                        is_dup = True
                        break
                # confirmations와 비교 (Hard 우선: LLM hard가 기존 soft와 겹으면 soft 제거)
                if not is_dup:
                    conf_parts = existing_desc_parts[len(reports):]
                    for ci, prev in enumerate(conf_parts):
                        if not prev:
                            continue
                        union = v_kw | prev
                        inter = v_kw & prev
                        if not union:
                            continue
                        jac = len(inter) / len(union)
                        if jac > 0.5 or (jac > 0.3 and len(inter) >= 3):
                            is_dup = True
                            dup_conf_idx = ci
                            break

            if is_dup:
                # Hard 우선: LLM hard + 기존 soft confirmation → soft 제거, hard 추가
                if v.get("is_hard") and dup_conf_idx >= 0 and dup_conf_idx < len(confirmations):
                    logger.debug("world_rule_hard_upgrade", desc=desc[:60])
                    confirmations.pop(dup_conf_idx)
                    existing_desc_parts.pop(len(reports) + dup_conf_idx)
                    reports.append(self._to_report(v))
                    existing_desc_parts.insert(len(reports) - 1, v_kw)
                    continue
                logger.debug("world_rule_cross_dedup_jaccard", desc=desc[:60])
                continue

            # 중복 아님 → 추가
            for ev_item in v.get("evidence", []):
                if isinstance(ev_item, dict):
                    rt = str(ev_item.get("rule", ""))
                    if rt and len(rt) > 10:
                        existing_fact_keys.add(rt[:60])
            existing_desc_parts.append(v_kw)
            if v.get("is_hard"):
                reports.append(self._to_report(v))
            else:
                confirmations.append(self._to_confirmation(v))

        # ── 최종 cross-dedup: reports와 confirmations 전체를 대상으로 ──
        # Hard report가 이미 잡은 내용이 Soft confirmation에도 있으면 confirmation 제거
        report_kw: List[set] = [self._extract_keywords(r.description) for r in reports]

        deduped_confirmations: List[UserConfirmation] = []
        for c in confirmations:
            c_kw = self._extract_keywords(c.question or c.context_summary)
            is_dup = False
            if c_kw and len(c_kw) >= 2:
                for rk in report_kw:
                    union = c_kw | rk
                    inter = c_kw & rk
                    if union and len(inter) / len(union) > 0.35:
                        is_dup = True
                        break
            if is_dup:
                logger.debug("final_dedup_confirmation_removed", q=c.question[:60] if c.question else "")
                continue
            deduped_confirmations.append(c)
        confirmations = deduped_confirmations

        # reports 내 자체 중복 제거 (keyword Jaccard 0.5 이상)
        deduped_reports: List[ContradictionReport] = []
        deduped_report_kw: List[set] = []
        for r in reports:
            r_kw = self._extract_keywords(r.description)
            is_dup = False
            if r_kw and len(r_kw) >= 2:
                for prev in deduped_report_kw:
                    union = r_kw | prev
                    inter = r_kw & prev
                    if union and len(inter) / len(union) > 0.5:
                        is_dup = True
                        break
            if is_dup:
                logger.debug("final_dedup_report_removed", desc=r.description[:60])
                continue
            deduped_reports.append(r)
            deduped_report_kw.append(r_kw)
        reports = deduped_reports

        elapsed = int(time.time() * 1000) - start
        logger.info(
            "analyze_complete",
            reports=len(reports),
            confirmations=len(confirmations),
            world_rule_violations=len(world_violations),
            elapsed_ms=elapsed,
        )
        return AnalysisResponse.from_contradictions(
            contradictions=reports,
            confirmations=confirmations,
            processing_time_ms=elapsed,
        )

    async def create_report_from_confirmation(
        self,
        confirmation_id: str,
        confirmation_type: ConfirmationType,
        question: str,
        context_summary: str,
        source_excerpts: List[SourceExcerpt],
        related_entity_ids: List[str],
        severity: Severity,
    ) -> ContradictionReport:
        """Phase 5에서 사용자가 confirmed_contradiction 결정 시 ContradictionReport 생성."""
        contradiction_type = _CONFIRMATION_TO_CONTRADICTION.get(
            confirmation_type, ContradictionType.ASYMMETRY
        )
        evidence = [
            EvidenceItem(
                source_name=e.source_name,
                source_location=e.source_location,
                text=e.text,
            )
            for e in source_excerpts
        ]
        report = ContradictionReport(
            id=f"report-{confirmation_id}",
            type=contradiction_type,
            severity=severity,
            hard_or_soft="soft",
            description=context_summary,
            evidence=evidence,
            confidence=1.0,
            suggestion=question,
            needs_user_input=False,
        )
        logger.info(
            "report_from_confirmation",
            confirmation_id=confirmation_id,
            contradiction_type=contradiction_type.value,
        )
        return report

    async def rerun_for_entities(
        self,
        entity_ids: List[str],
        reason: str = "",
    ) -> None:
        """Phase 5 피드백 루프: 특정 엔티티에 대해 재탐지를 요청.

        실제 재탐지는 graph_service 접근이 필요하므로
        full_scan()을 통해 호출자가 직접 수행해야 합니다.
        """
        logger.info(
            "rerun_for_entities_requested",
            entity_ids=entity_ids,
            reason=reason,
            note="graph_service 없이 호출됨 — 호출자가 full_scan()으로 재탐지 수행 필요",
        )

    async def full_scan(self, graph_service) -> AnalysisResponse:
        """전체 canonical graph 전수조사."""
        start = int(time.time() * 1000)
        violations = graph_service.find_all_violations()
        return await self.analyze(violations, start, graph_service=graph_service)

    # ── 단일 후보 검증 (하위 호환) ────────────────────────────

    async def verify_violation(self, violation_data: Dict[str, Any]) -> ContradictionVerification:
        """그래프 엔진에서 발견된 모순 후보를 LLM이 정밀 검증합니다."""
        if self._mock_mode:
            return ContradictionVerification(
                is_contradiction=True,
                confidence=0.5,
                severity="major",
                reasoning="LLM 검증 비활성화 (API 키 없음) — 사용자 확인 필요",
                user_question="LLM 검증 없이 자동 판정할 수 없습니다. 수동 검토가 필요합니다.",
            )

        logger.info("Starting LLM verification for violation", violation_type=violation_data.get("type"))
        prompt = CONTRADICTION_PROMPT.format(violation_data=str(violation_data))
        try:
            response = await self.client.beta.chat.completions.parse(
                model=self.deployment_name,
                messages=[
                    {"role": "system", "content": "당신은 서사 정합성 및 논리 구조 분석 전문가입니다."},
                    {"role": "user", "content": prompt},
                ],
                response_format=ContradictionVerification,
            )
            verification_result = response.choices[0].message.parsed
            if response.usage:
                from app.services.cost_tracker import get_tracker
                get_tracker().add(self.deployment_name, response.usage)
            logger.info(
                "LLM Verification complete",
                is_contradiction=verification_result.is_contradiction,
                confidence=verification_result.confidence,
            )
            return verification_result
        except Exception as e:
            logger.error("LLM Verification failed", error=str(e))
            return ContradictionVerification(
                is_contradiction=True,
                confidence=0.0,
                severity="major",
                reasoning=f"검증 엔진 내부 오류로 자동 분석 실패: {str(e)}",
                user_question="시스템 오류로 인해 수동 검토가 필요합니다.",
            )