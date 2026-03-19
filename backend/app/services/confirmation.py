"""
confirmation.py — 계층 5: 사용자 확인 관리 서비스

책임:
  1. create_confirmation  — UserConfirmation 생성 (source_excerpts 필수)
  2. list_pending         — 미해결 확인 목록 조회
  3. resolve              — 사용자 응답 처리 + 피드백 루프
  4. get_source_excerpts  — SearchService를 통한 원본 발췌 조회

피드백 루프 (resolve 후):
  flashback_check 해결    → Event.story_order 확정 + is_linear=false → 계층4 재탐지
  source_conflict 해결    → 비정본 Source 비활성화 → 계층3 그래프 업데이트
  intentional_change 해결 → Trait valid_until 설정 → 계층3 업데이트
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import structlog

from app.models.enums import ConfirmationType, Severity
from app.models.vertices import SourceExcerpt, UserConfirmation

if TYPE_CHECKING:
    from app.services.detection import DetectionService
    from app.services.graph import GraphService
    from app.services.search import SearchService

logger = structlog.get_logger(__name__)

# resolve()에서 허용되는 decision 값
VALID_DECISIONS: frozenset[str] = frozenset(
    {"confirmed_contradiction", "confirmed_intentional", "deferred"}
)


# ──────────────────────────────────────────────────────────────────────────────
# 예외
# ──────────────────────────────────────────────────────────────────────────────


class ConfirmationError(Exception):
    """사용자 확인 서비스 관련 오류의 기반 클래스."""


class MissingSourceExcerptsError(ConfirmationError):
    """원본 발췌(source_excerpts) 없이 확인을 생성하려 할 때 발생."""


class ConfirmationNotFoundError(ConfirmationError):
    """주어진 ID에 해당하는 UserConfirmation이 없을 때 발생."""


class AlreadyResolvedError(ConfirmationError):
    """이미 처리된 확인에 대해 resolve를 재시도할 때 발생."""


# ──────────────────────────────────────────────────────────────────────────────
# ConfirmationService
# ──────────────────────────────────────────────────────────────────────────────


class ConfirmationService:
    """
    계층 5: 사용자 확인 생성·조회·해결 및 그래프 피드백 루프 처리.

    사용 예::

        svc = ConfirmationService(graph, search, detection)

        # 확인 생성
        conf = await svc.create_confirmation(
            confirmation_type=ConfirmationType.FLASHBACK_CHECK,
            question="이 장면은 회상 씬인가요?",
            context="Chapter 3에서 A가 과거 사건을 떠올리는 묘사가 등장합니다.",
            source_excerpts=[excerpt1, excerpt2],
            entity_ids=["event-uuid-1234"],
        )

        # 해결
        resolved = await svc.resolve(
            confirmation_id=conf.id,
            user_response="네, 의도된 회상입니다. story_order: 1.5",
            decision="confirmed_intentional",
        )
    """

    def __init__(
        self,
        graph_service: "GraphService",
        search_service: "SearchService",
        detection_service: Optional["DetectionService"] = None,
    ) -> None:
        self._graph = graph_service
        self._search = search_service
        self._detection = detection_service
        self._log = logger.bind(service="ConfirmationService")

    # ──────────────────────────────────────────────────────────────
    # 1. 확인 생성
    # ──────────────────────────────────────────────────────────────

    async def create_confirmation(
        self,
        confirmation_type: ConfirmationType,
        question: str,
        context: str,
        source_excerpts: list[SourceExcerpt],
        entity_ids: list[str],
    ) -> UserConfirmation:
        """
        새 UserConfirmation Vertex를 생성하고 그래프에 저장합니다.

        Parameters
        ----------
        confirmation_type:
            9가지 확인 유형 중 하나
            (flashback_check / intentional_change / foreshadowing /
             source_conflict / emotion_shift / relationship_ambiguity /
             item_discrepancy / timeline_ambiguity / unreliable_narrator)
        question:
            사용자에게 표시할 질문 문자열
        context:
            질문의 맥락 요약 (장(chapter), 등장인물 등)
        source_excerpts:
            원본 발췌 목록 — **최소 1개 필수**. 없으면 MissingSourceExcerptsError.
        entity_ids:
            이 확인과 관련된 Vertex ID 목록 (Event, Trait, Source 등)

        Returns
        -------
        UserConfirmation
            status='pending'으로 생성된 확인 객체

        Raises
        ------
        MissingSourceExcerptsError
            source_excerpts가 빈 리스트인 경우
        ConfirmationError
            그래프 저장 실패 시
        """
        if not source_excerpts:
            raise MissingSourceExcerptsError(
                "source_excerpts는 1개 이상 필수입니다. "
                "원본 발췌 없이 UserConfirmation을 생성할 수 없습니다."
            )

        log = self._log.bind(
            confirmation_type=confirmation_type.value,
            entity_ids=entity_ids,
        )
        log.info("confirmation_creating")

        confirmation = UserConfirmation(
            id=str(uuid.uuid4()),
            confirmation_type=confirmation_type,
            status="pending",
            question=question,
            context_summary=context,
            source_excerpts=source_excerpts,
            related_entity_ids=entity_ids,
            source_id="system",
            partition_key="confirmation",
        )

        try:
            await self._graph.upsert_vertex(confirmation)
        except Exception as exc:
            log.error("confirmation_save_failed", error=str(exc))
            raise ConfirmationError(f"UserConfirmation 저장 실패: {exc}") from exc

        log.info("confirmation_created", confirmation_id=confirmation.id)
        return confirmation

    # ──────────────────────────────────────────────────────────────
    # 2. 미해결 목록 조회
    # ──────────────────────────────────────────────────────────────

    async def list_pending(self) -> list[UserConfirmation]:
        """
        status='pending'인 UserConfirmation 전체를 반환합니다.

        Returns
        -------
        list[UserConfirmation]
            생성 시각 오름차순 정렬

        Raises
        ------
        ConfirmationError
            그래프 조회 실패 시
        """
        log = self._log.bind(action="list_pending")
        try:
            raw_list: list[dict] = await self._graph.query_vertices(
                partition_key="confirmation",
                filters={"status": "pending"},
            )
            result = [UserConfirmation(**raw) for raw in raw_list]
            # 생성 시각 오름차순 (오래된 것을 먼저 처리)
            result.sort(key=lambda c: c.created_at)
            log.info("pending_confirmations_fetched", count=len(result))
            return result
        except Exception as exc:
            log.error("list_pending_failed", error=str(exc))
            raise ConfirmationError(f"미해결 목록 조회 실패: {exc}") from exc

    # ──────────────────────────────────────────────────────────────
    # 3. 해결(resolve) + 피드백 루프
    # ──────────────────────────────────────────────────────────────

    async def resolve(
        self,
        confirmation_id: str,
        user_response: str,
        decision: str,
    ) -> UserConfirmation:
        """
        사용자 응답을 받아 확인을 해결하고 피드백 루프를 실행합니다.

        Parameters
        ----------
        confirmation_id:
            처리할 UserConfirmation의 ID
        user_response:
            사용자의 자유 텍스트 응답
            - source_conflict 시 정본 지정: ``"canonical:<source_id>"``
            - flashback_check 시 story_order 지정: ``"story_order:1.5"``
        decision:
            처리 방향
            - ``"confirmed_contradiction"``
              → DetectionService에 ContradictionReport 생성 요청
            - ``"confirmed_intentional"``
              → 그래프 업데이트 + 확인 유형별 피드백 루프
            - ``"deferred"``
              → 상태를 'deferred'로만 변경 (피드백 루프 없음)

        Returns
        -------
        UserConfirmation
            업데이트된 확인 객체

        Raises
        ------
        ValueError
            decision 값이 허용 범위 밖인 경우
        ConfirmationNotFoundError
            해당 ID의 확인이 없을 때
        AlreadyResolvedError
            이미 처리된 확인을 재시도할 때
        ConfirmationError
            그래프 저장 실패 또는 피드백 루프 오류 시
        """
        if decision not in VALID_DECISIONS:
            raise ValueError(
                f"잘못된 decision 값: '{decision}'. "
                f"허용값: {sorted(VALID_DECISIONS)}"
            )

        log = self._log.bind(confirmation_id=confirmation_id, decision=decision)
        log.info("confirmation_resolving")

        # ── 대상 확인 로드 ─────────────────────────────────────────
        confirmation = await self._load_confirmation(confirmation_id)
        if confirmation.status != "pending":
            raise AlreadyResolvedError(
                f"이미 처리된 확인입니다 "
                f"(id={confirmation_id}, status={confirmation.status})"
            )

        # ── 공통 메타 업데이트 ──────────────────────────────────────
        confirmation.user_response = user_response
        confirmation.resolved_at = datetime.now(tz=timezone.utc)

        # ── decision별 1차 처리 ────────────────────────────────────
        if decision == "confirmed_contradiction":
            confirmation.status = "resolved"
            await self._handle_confirmed_contradiction(confirmation, log)

        elif decision == "confirmed_intentional":
            confirmation.status = "resolved"
            await self._handle_confirmed_intentional(confirmation, log)

        else:  # deferred
            confirmation.status = "deferred"
            log.info("confirmation_deferred")

        # ── 변경 저장 ──────────────────────────────────────────────
        try:
            await self._graph.upsert_vertex(confirmation)
        except Exception as exc:
            log.error("confirmation_update_failed", error=str(exc))
            raise ConfirmationError(f"확인 상태 저장 실패: {exc}") from exc

        # ── 피드백 루프: confirmed_intentional일 때만 실행 ────────
        # confirmed_contradiction → DetectionService 리포트 생성으로 종료.
        #   그래프 피드백 루프까지 이어지면 중복 재탐지가 발생한다.
        # deferred              → 상태 변경만. 피드백 루프 없음.
        if decision == "confirmed_intentional":
            await self._run_feedback_loop(confirmation, decision, log)

        log.info("confirmation_resolved", final_status=confirmation.status)
        return confirmation

    # ──────────────────────────────────────────────────────────────
    # 4. 원본 발췌 조회
    # ──────────────────────────────────────────────────────────────

    async def get_source_excerpts(
        self,
        entity_ids: list[str],
    ) -> list[SourceExcerpt]:
        """
        SearchService를 통해 entity_ids에 해당하는 원본 발췌를 반환합니다.
        UserConfirmation 생성 직전에 호출하여 source_excerpts를 채웁니다.

        Parameters
        ----------
        entity_ids:
            원본 발췌를 가져올 Vertex ID 목록

        Returns
        -------
        list[SourceExcerpt]
            각 엔티티에 대응하는 원본 텍스트 + 위치 정보

        Raises
        ------
        ConfirmationError
            SearchService 조회 실패 시
        """
        log = self._log.bind(entity_ids=entity_ids, action="get_source_excerpts")
        try:
            excerpts: list[SourceExcerpt] = await self._search.get_source_excerpts(
                entity_ids
            )
            log.info("source_excerpts_fetched", count=len(excerpts))
            return excerpts
        except Exception as exc:
            log.error("get_source_excerpts_failed", error=str(exc))
            raise ConfirmationError(f"원본 발췌 검색 실패: {exc}") from exc

    # ──────────────────────────────────────────────────────────────
    # Private: decision별 1차 처리
    # ──────────────────────────────────────────────────────────────

    async def _handle_confirmed_contradiction(
        self,
        confirmation: UserConfirmation,
        log: structlog.BoundLogger,
    ) -> None:
        """
        confirmed_contradiction:
        DetectionService에 ContradictionReport 생성을 요청합니다.
        DetectionService가 주입되지 않은 경우 경고만 기록하고 통과합니다.
        """
        if self._detection is None:
            log.warning(
                "detection_service_unavailable",
                detail="ContradictionReport를 자동 생성할 수 없습니다. "
                       "ConfirmationService 생성 시 detection_service를 주입해 주세요.",
            )
            return

        try:
            await self._detection.create_report_from_confirmation(
                confirmation_id=confirmation.id,
                confirmation_type=confirmation.confirmation_type,
                question=confirmation.question,
                context_summary=confirmation.context_summary,
                source_excerpts=confirmation.source_excerpts,
                related_entity_ids=confirmation.related_entity_ids,
                severity=Severity.WARNING,
            )
            log.info(
                "contradiction_report_created",
                confirmation_id=confirmation.id,
            )
        except Exception as exc:
            log.error("report_creation_failed", error=str(exc))
            raise ConfirmationError(f"모순 리포트 생성 요청 실패: {exc}") from exc

    async def _handle_confirmed_intentional(
        self,
        confirmation: UserConfirmation,
        log: structlog.BoundLogger,
    ) -> None:
        """
        confirmed_intentional: 확인 유형별로 그래프 Vertex를 업데이트합니다.

        유형별 처리:
          INTENTIONAL_CHANGE → Trait.valid_until을 현재 시각으로 설정
                               ("이 설정은 이 지점까지만 유효했다"는 의미)
          SOURCE_CONFLICT    → 비정본 Source.status = 'inactive'
          FLASHBACK_CHECK    → Event.story_order 확정 + is_linear=False
          기타               → 그래프 변경 없음 (피드백 루프에서 처리)
        """
        ctype = confirmation.confirmation_type
        log.info("handling_intentional", confirmation_type=ctype.value)

        if ctype == ConfirmationType.INTENTIONAL_CHANGE:
            await self._set_trait_valid_until(confirmation, log)

        elif ctype == ConfirmationType.SOURCE_CONFLICT:
            await self._deactivate_non_canonical_sources(confirmation, log)

        elif ctype == ConfirmationType.FLASHBACK_CHECK:
            await self._confirm_nonlinear_event(confirmation, log)

        else:
            log.debug(
                "no_graph_update_for_type",
                confirmation_type=ctype.value,
                detail="피드백 루프에서 처리되거나 그래프 변경이 불필요한 유형입니다.",
            )

    # ──────────────────────────────────────────────────────────────
    # Private: 그래프 업데이트 서브루틴
    # ──────────────────────────────────────────────────────────────

    async def _set_trait_valid_until(
        self,
        confirmation: UserConfirmation,
        log: structlog.BoundLogger,
    ) -> None:
        """
        INTENTIONAL_CHANGE 처리:
        관련 Trait 노드에 valid_until을 현재 시각으로 설정합니다.
        "이 설정은 여기까지만 유효하며, 이후의 변화는 의도된 것이다"를 표현합니다.
        """
        now_iso = datetime.now(tz=timezone.utc).isoformat()
        for entity_id in confirmation.related_entity_ids:
            try:
                await self._graph.patch_vertex(
                    vertex_id=entity_id,
                    partition_key="trait",
                    fields={"valid_until": now_iso},
                )
                log.info("trait_valid_until_set", trait_id=entity_id, valid_until=now_iso)
            except Exception as exc:
                # 일부 실패해도 나머지를 계속 처리
                log.warning(
                    "trait_patch_failed",
                    trait_id=entity_id,
                    error=str(exc),
                )

    async def _deactivate_non_canonical_sources(
        self,
        confirmation: UserConfirmation,
        log: structlog.BoundLogger,
    ) -> None:
        """
        SOURCE_CONFLICT 처리:
        user_response에서 정본 source_id를 파싱하고,
        나머지 related Source 노드를 status='inactive'로 설정합니다.
        """
        canonical_id = _parse_canonical_source(confirmation.user_response)
        log.info(
            "deactivating_non_canonical_sources",
            canonical_id=canonical_id,
            related_ids=confirmation.related_entity_ids,
        )

        for entity_id in confirmation.related_entity_ids:
            if entity_id == canonical_id:
                continue  # 정본은 건드리지 않음
            try:
                await self._graph.patch_vertex(
                    vertex_id=entity_id,
                    partition_key="source",
                    fields={"status": "inactive"},
                )
                log.info("non_canonical_source_deactivated", source_id=entity_id)
            except Exception as exc:
                log.warning(
                    "source_deactivation_failed",
                    source_id=entity_id,
                    error=str(exc),
                )

    async def _confirm_nonlinear_event(
        self,
        confirmation: UserConfirmation,
        log: structlog.BoundLogger,
    ) -> None:
        """
        FLASHBACK_CHECK 처리:
        user_response에서 story_order를 파싱하고
        Event 노드에 story_order + is_linear=False를 설정합니다.
        """
        story_order = _parse_story_order(confirmation.user_response)
        fields: dict = {"is_linear": False}
        if story_order is not None:
            fields["story_order"] = story_order

        for entity_id in confirmation.related_entity_ids:
            try:
                await self._graph.patch_vertex(
                    vertex_id=entity_id,
                    partition_key="event",
                    fields=fields,
                )
                log.info(
                    "event_nonlinear_confirmed",
                    event_id=entity_id,
                    story_order=story_order,
                    is_linear=False,
                )
            except Exception as exc:
                log.warning(
                    "event_patch_failed",
                    event_id=entity_id,
                    error=str(exc),
                )

    # ──────────────────────────────────────────────────────────────
    # Private: 피드백 루프 디스패처
    # ──────────────────────────────────────────────────────────────

    async def _run_feedback_loop(
        self,
        confirmation: UserConfirmation,
        decision: str,
        log: structlog.BoundLogger,
    ) -> None:
        """
        해결 후 확인 유형별 피드백 루프를 실행합니다.

        ┌────────────────────────┬────────────────────────────────────────────────┐
        │ 유형                    │ 피드백 루프                                     │
        ├────────────────────────┼────────────────────────────────────────────────┤
        │ FLASHBACK_CHECK        │ story_order 확정 → 계층4(Detection) 재탐지      │
        │ SOURCE_CONFLICT        │ 비정본 비활성화 → 계층3(Graph) canonical rebuild │
        │ INTENTIONAL_CHANGE     │ Trait valid_until → 계층3 violation 정리        │
        │ 기타                    │ 피드백 루프 없음                                 │
        └────────────────────────┴────────────────────────────────────────────────┘
        """
        ctype = confirmation.confirmation_type
        log.info("feedback_loop_start", confirmation_type=ctype.value, decision=decision)

        if ctype == ConfirmationType.FLASHBACK_CHECK:
            await self._feedback_flashback(confirmation, log)

        elif ctype == ConfirmationType.SOURCE_CONFLICT:
            await self._feedback_source_conflict(confirmation, log)

        elif ctype == ConfirmationType.INTENTIONAL_CHANGE:
            await self._feedback_intentional_change(confirmation, log)

        else:
            log.debug("no_feedback_loop", confirmation_type=ctype.value)

    async def _feedback_flashback(
        self,
        confirmation: UserConfirmation,
        log: structlog.BoundLogger,
    ) -> None:
        """
        FLASHBACK_CHECK 피드백 루프:
        그래프 업데이트(_confirm_nonlinear_event)는 이미 완료됨.
        이어서 계층4 DetectionService를 재트리거합니다.

        재탐지 이유: story_order가 확정됨으로써 이전에 story_order=null 때문에
        스킵했던 정보 비대칭, 타임라인 모순이 새로 감지될 수 있습니다.
        """
        log.info("feedback_flashback", confirmation_id=confirmation.id)

        if self._detection is None:
            log.warning(
                "detection_service_unavailable_skip_redetect",
                detail="DetectionService가 없어 재탐지를 건너뜁니다.",
            )
            return

        try:
            await self._detection.rerun_for_entities(
                entity_ids=confirmation.related_entity_ids,
                reason=f"flashback_check resolved — confirmation_id={confirmation.id}",
            )
            log.info(
                "redetection_triggered",
                entity_ids=confirmation.related_entity_ids,
            )
        except Exception as exc:
            # 재탐지 실패는 전체 resolve를 실패시키지 않음 (경고만)
            log.error("redetection_failed", error=str(exc))

    async def _feedback_source_conflict(
        self,
        confirmation: UserConfirmation,
        log: structlog.BoundLogger,
    ) -> None:
        """
        SOURCE_CONFLICT 피드백 루프:
        비정본 비활성화는 이미 완료됨.
        GraphService에 canonical source 기반 재구축을 요청합니다.
        """
        canonical_id = _parse_canonical_source(confirmation.user_response)
        log.info("feedback_source_conflict", canonical_id=canonical_id)

        if not canonical_id:
            log.warning(
                "canonical_id_not_parsed",
                user_response=confirmation.user_response,
                detail="정본 source_id를 파싱할 수 없어 그래프 재구축을 건너뜁니다.",
            )
            return

        try:
            await self._graph.rebuild_from_canonical_source(canonical_id)
            log.info("graph_rebuilt_from_canonical", canonical_id=canonical_id)
        except Exception as exc:
            log.error("graph_rebuild_failed", error=str(exc))

    async def _feedback_intentional_change(
        self,
        confirmation: UserConfirmation,
        log: structlog.BoundLogger,
    ) -> None:
        """
        INTENTIONAL_CHANGE 피드백 루프:
        Trait valid_until 설정은 이미 완료됨.
        해당 Trait에 연결된 VIOLATES_TRAIT 엣지를
        '의도된 변화(intentional)'로 마킹하여 계층3을 정리합니다.
        """
        log.info("feedback_intentional_change", entity_ids=confirmation.related_entity_ids)

        for entity_id in confirmation.related_entity_ids:
            try:
                await self._graph.resolve_trait_violation(
                    trait_id=entity_id,
                    confirmation_id=confirmation.id,
                )
                log.info("trait_violation_resolved", trait_id=entity_id)
            except Exception as exc:
                log.warning(
                    "trait_violation_cleanup_failed",
                    trait_id=entity_id,
                    error=str(exc),
                )

    # ──────────────────────────────────────────────────────────────
    # Private: 그래프 조회 헬퍼
    # ──────────────────────────────────────────────────────────────

    async def _load_confirmation(self, confirmation_id: str) -> UserConfirmation:
        """
        ID로 UserConfirmation Vertex를 그래프에서 불러옵니다.

        Raises
        ------
        ConfirmationNotFoundError
            해당 ID의 Vertex가 없을 때
        ConfirmationError
            그래프 조회 실패 시
        """
        try:
            raw = await self._graph.get_vertex(
                vertex_id=confirmation_id,
                partition_key="confirmation",
            )
        except Exception as exc:
            raise ConfirmationError(
                f"확인 조회 중 그래프 오류: {exc}"
            ) from exc

        if raw is None:
            raise ConfirmationNotFoundError(
                f"UserConfirmation을 찾을 수 없습니다: id={confirmation_id}"
            )
        return UserConfirmation(**raw)


# ──────────────────────────────────────────────────────────────────────────────
# 모듈 레벨 파싱 헬퍼 (순수 함수 — 테스트 용이성을 위해 클래스 밖에 위치)
# ──────────────────────────────────────────────────────────────────────────────


def _parse_canonical_source(user_response: str) -> str:
    """
    user_response에서 정본 source_id를 추출합니다.

    파싱 규칙 (우선순위 순):
    1. ``"canonical:<source_id>"`` 형식 → source_id 반환
    2. 응답이 단일 토큰 → 그 자체를 ID로 간주
    3. 그 외 → 빈 문자열 반환 (호출자가 경고 처리)

    Examples
    --------
    >>> _parse_canonical_source("canonical:src-uuid-5678")
    'src-uuid-5678'
    >>> _parse_canonical_source("src-uuid-5678")
    'src-uuid-5678'
    >>> _parse_canonical_source("잘 모르겠습니다")
    ''
    """
    response = user_response.strip()
    if not response:
        return ""

    if response.startswith("canonical:"):
        return response.split("canonical:", 1)[1].strip()

    tokens = response.split()
    if len(tokens) == 1:
        return tokens[0]

    return ""


def _parse_story_order(user_response: str) -> float | None:
    """
    user_response에서 story_order 값(float)을 추출합니다.

    파싱 규칙:
    - ``"story_order:<float>"`` 형식에서 추출
    - 형식이 없거나 변환 불가 시 None 반환

    Examples
    --------
    >>> _parse_story_order("네, 회상입니다. story_order:1.5")
    1.5
    >>> _parse_story_order("의도된 플래시백입니다")
    None
    """
    if "story_order:" not in user_response:
        return None
    try:
        raw = user_response.split("story_order:", 1)[1].strip().split()[0]
        return float(raw)
    except (ValueError, IndexError):
        return None