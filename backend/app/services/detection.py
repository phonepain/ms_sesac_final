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
            logger.info(
                "soft_llm_verify",
                confidence=result.confidence,
                is_contradiction=result.is_contradiction,
            )
            return result.confidence, result.reasoning
        except Exception as e:
            logger.error("soft_llm_verify_failed", error=str(e))
            return 0.0, f"검증 오류: {str(e)}"

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

        # Soft: LLM 검증 후 분기
        for v in violations.get("soft", []):
            confidence, reasoning = await self._verify_soft_with_llm(v)
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

    async def analyze(
        self,
        violations: Dict[str, List],
        processing_start_ms: Optional[int] = None,
    ) -> AnalysisResponse:
        """violations dict → AnalysisResponse.

        agent.py에서 스냅샷 격리 후 find_all_violations() 결과를 여기로 전달.
        """
        start = processing_start_ms or int(time.time() * 1000)
        reports, confirmations = await self.process_violations(violations)
        elapsed = int(time.time() * 1000) - start
        logger.info(
            "analyze_complete",
            reports=len(reports),
            confirmations=len(confirmations),
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
        return await self.analyze(violations, start)

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