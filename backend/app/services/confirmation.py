"""
계층 5 — 사용자 확인 서비스 (ConfirmationService)

역할:
  - UserConfirmation 생성 / 조회 / 해결
  - 해결 결정에 따른 피드백 루프 (그래프 업데이트 → 계층 4 재탐지)
  - SearchService 연동으로 원본 발췌 수집
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional, TYPE_CHECKING

import structlog

from app.models.enums import (
    ConfirmationType,
    ConfirmationStatus,
)
from app.models.vertices import UserConfirmation, SourceExcerpt
from app.services.search import get_search_service

if TYPE_CHECKING:
    # 순환 임포트 방지: 타입 힌트 전용
    from app.services.graph import InMemoryGraphService  # noqa: F401

logger = structlog.get_logger().bind(service="confirmation_service")


# ─────────────────────────────────────────────────────────────
# 헬퍼
# ─────────────────────────────────────────────────────────────

def _now_str() -> str:
    return datetime.utcnow().isoformat()


def _make_source_excerpt(source_name: str, source_location: str, text: str) -> SourceExcerpt:
    return SourceExcerpt(
        source_id="search",
        source_name=source_name,
        source_location=source_location,
        text=text,
    )


# ─────────────────────────────────────────────────────────────
# ConfirmationService
# ─────────────────────────────────────────────────────────────

class ConfirmationService:
    """사용자 확인(UserConfirmation) CRUD + 피드백 루프 관리"""

    def __init__(self, graph_service):
        """
        Parameters
        ----------
        graph_service : GremlinGraphService | InMemoryGraphService
            계층 3 그래프 서비스 인스턴스
        """
        self.graph = graph_service
        self.search = get_search_service()

    # ── 생성 ─────────────────────────────────────────────────

    def create_confirmation(
        self,
        confirmation_type: ConfirmationType,
        question: str,
        context_summary: str,
        related_entity_ids: List[str],
        source_excerpts: Optional[List[SourceExcerpt]] = None,
        source_id: str = "system",
    ) -> UserConfirmation:
        """
        UserConfirmation을 생성하고 그래프에 저장합니다.

        Parameters
        ----------
        source_excerpts : list[SourceExcerpt] | None
            원본 발췌가 없으면 SearchService에서 자동 수집합니다.
            원본 없이 생성되는 것을 막기 위해 비어 있으면 경고 로그를 출력합니다.
        """
        # 원본 발췌 자동 수집 (없는 경우)
        if not source_excerpts:
            logger.warning(
                "source_excerpts not provided — attempting auto-fetch from SearchService",
                entity_ids=related_entity_ids,
            )
            evidence_items = self.search.get_source_excerpts(related_entity_ids)
            source_excerpts = [
                _make_source_excerpt(e.source_name, e.source_location, e.text)
                for e in evidence_items
            ]

        if not source_excerpts:
            logger.warning(
                "No source excerpts found. Confirmation will be created without evidence.",
                type=confirmation_type,
            )

        conf = UserConfirmation(
            source_id=source_id,
            confirmation_type=confirmation_type,
            status=ConfirmationStatus.PENDING,
            question=question,
            context_summary=context_summary,
            source_excerpts=source_excerpts,
            related_entity_ids=related_entity_ids,
        )

        from app.services.graph import _vertex_to_dict  # 지연 임포트
        conf_dict = _vertex_to_dict(conf)
        self.graph.add_user_confirmation(conf_dict)

        logger.info(
            "UserConfirmation created",
            conf_id=str(conf.id),
            type=confirmation_type.value,
        )
        return conf

    # ── 조회 ─────────────────────────────────────────────────

    def list_pending(self) -> List[UserConfirmation]:
        """PENDING 상태의 UserConfirmation 목록 반환"""
        raw_list = self.graph.list_pending_confirmations()
        return [self._dict_to_model(d) for d in raw_list if d]

    def get(self, conf_id: str) -> Optional[UserConfirmation]:
        """단일 UserConfirmation 조회"""
        raw = self.graph.get_user_confirmation(conf_id)
        if not raw:
            return None
        return self._dict_to_model(raw)

    # ── 해결 ─────────────────────────────────────────────────

    def resolve(
        self,
        conf_id: str,
        user_response: str,
        decision: ConfirmationStatus,
    ) -> Optional[UserConfirmation]:
        """
        UserConfirmation을 해결합니다.

        Parameters
        ----------
        decision : ConfirmationStatus
            - CONFIRMED_CONTRADICTION : 실제 모순 → 리포트로 전환
            - CONFIRMED_INTENTIONAL   : 의도적 작가 선택 → 그래프에 valid_until 등 반영
            - DEFERRED                : 나중에 다시 확인
        """
        conf = self.get(conf_id)
        if conf is None:
            logger.warning("Confirmation not found", conf_id=conf_id)
            return None

        if conf.status != ConfirmationStatus.PENDING:
            logger.warning(
                "Confirmation already resolved",
                conf_id=conf_id,
                current_status=conf.status,
            )
            return conf

        # 상태 업데이트
        conf.status = decision
        conf.user_response = user_response
        conf.resolved_at = datetime.utcnow()

        self._persist_update(conf)

        logger.info(
            "UserConfirmation resolved",
            conf_id=conf_id,
            decision=decision.value,
        )

        # 피드백 루프
        if decision == ConfirmationStatus.CONFIRMED_INTENTIONAL:
            self._apply_intentional_feedback(conf)
        elif decision == ConfirmationStatus.CONFIRMED_CONTRADICTION:
            self._apply_contradiction_feedback(conf)
        # DEFERRED: 상태만 변경, 별도 처리 없음

        return conf

    # ── 원본 발췌 수집 ────────────────────────────────────────

    def get_source_excerpts(self, entity_ids: List[str]) -> List[SourceExcerpt]:
        """SearchService를 이용해 관련 원본 발췌를 수집합니다."""
        evidence_items = self.search.get_source_excerpts(entity_ids)
        return [
            _make_source_excerpt(e.source_name, e.source_location, e.text)
            for e in evidence_items
        ]

    # ── 피드백 루프 ───────────────────────────────────────────

    def _apply_intentional_feedback(self, conf: UserConfirmation) -> None:
        """
        의도적 변경으로 확인된 경우의 그래프 업데이트.

        확인 유형별 처리:
        - flashback_check      : Event.story_order 확정 + is_linear=False
        - source_conflict      : 비정본(canonical=False) 소스 비활성화
        - intentional_change   : Trait valid_until 설정 (변화 인정)
        - emotion_shift        : 감정 변화 이유가 확인됨 → 경고 해제
        - 나머지               : 관련 엔티티에 'intentional=true' 마킹
        """
        ctype = conf.confirmation_type
        entity_ids = conf.related_entity_ids

        if ctype == ConfirmationType.FLASHBACK_CHECK:
            self._handle_flashback_confirmed(entity_ids, conf.user_response or "")

        elif ctype == ConfirmationType.SOURCE_CONFLICT:
            self._handle_source_conflict_resolved(entity_ids)

        elif ctype == ConfirmationType.INTENTIONAL_CHANGE:
            self._handle_trait_change_confirmed(entity_ids)

        elif ctype == ConfirmationType.EMOTION_SHIFT:
            logger.info("Emotion shift confirmed as intentional", entity_ids=entity_ids)

        else:
            # 범용 마킹 — 그래프 서비스에 구현된 경우만
            self._mark_entities_intentional(entity_ids)

        logger.info(
            "Intentional feedback applied",
            conf_id=str(conf.id),
            type=ctype.value,
        )

    def _apply_contradiction_feedback(self, conf: UserConfirmation) -> None:
        """
        실제 모순으로 확인된 경우의 처리.
        - 그래프에 'confirmed_contradiction=true' 마킹
        - 계층 4 재탐지는 호출자(API 레이어)가 책임짐
        """
        self._mark_entities_contradiction(conf.related_entity_ids)
        logger.info(
            "Contradiction feedback applied",
            conf_id=str(conf.id),
            type=conf.confirmation_type.value,
        )

    # ── 확인 유형별 그래프 업데이트 ──────────────────────────

    def _handle_flashback_confirmed(self, entity_ids: List[str], user_response: str) -> None:
        """
        회상/플래시백이 확인된 경우.
        관련 Event vertex의 is_linear=False, story_order 확정.
        """
        for eid in entity_ids:
            v = self._get_vertex(eid)
            if v and v.get("label") == "event":
                self._update_vertex_props(eid, {"is_linear": False})
                logger.info("Event marked non-linear (flashback confirmed)", event_id=eid)

    def _handle_source_conflict_resolved(self, entity_ids: List[str]) -> None:
        """
        소스 충돌이 해결된 경우.
        사용자가 정본(canonical)을 선택했다고 가정하고,
        나머지 소스를 'inactive' 상태로 변경.
        entity_ids의 첫 번째를 정본으로, 나머지를 비정본으로 처리.
        """
        if len(entity_ids) < 2:
            return
        canonical_id = entity_ids[0]
        for eid in entity_ids[1:]:
            self._update_vertex_props(eid, {"status": "inactive", "is_canonical": False})
            logger.info("Source marked inactive (conflict resolved)", source_id=eid)
        self._update_vertex_props(canonical_id, {"is_canonical": True})

    def _handle_trait_change_confirmed(self, entity_ids: List[str]) -> None:
        """
        캐릭터 특성 변화가 의도적임이 확인된 경우.
        이전 Trait vertex에 valid_until 설정(현재 시각).
        """
        for eid in entity_ids:
            v = self._get_vertex(eid)
            if v and v.get("label") == "trait":
                # valid_until을 현재 discourse_order 이전으로 마킹
                self._update_vertex_props(eid, {"valid_until": _now_str(), "intentional": True})
                logger.info("Trait valid_until set (intentional change)", trait_id=eid)

    def _mark_entities_intentional(self, entity_ids: List[str]) -> None:
        """범용 intentional 마킹"""
        for eid in entity_ids:
            self._update_vertex_props(eid, {"intentional": True})

    def _mark_entities_contradiction(self, entity_ids: List[str]) -> None:
        """범용 confirmed_contradiction 마킹"""
        for eid in entity_ids:
            self._update_vertex_props(eid, {"confirmed_contradiction": True})

    # ── 그래프 저수준 헬퍼 ───────────────────────────────────

    def _get_vertex(self, vid: str) -> Optional[dict]:
        """그래프 서비스에서 단일 vertex 조회 (서비스 종류에 상관없이)"""
        # InMemoryGraphService: self.graph.vertices
        if hasattr(self.graph, "vertices"):
            return self.graph.vertices.get(vid)
        # GremlinGraphService: 직접 쿼리
        try:
            result = self.graph.g.V(vid).valueMap(True).toList()
            return result[0] if result else None
        except Exception as e:
            logger.error("Failed to get vertex", vid=vid, error=str(e))
            return None

    def _update_vertex_props(self, vid: str, props: dict) -> None:
        """vertex 속성을 업데이트합니다."""
        # InMemoryGraphService
        if hasattr(self.graph, "vertices") and vid in self.graph.vertices:
            self.graph.vertices[vid].update(props)
            return
        # GremlinGraphService
        try:
            t = self.graph.g.V(vid)
            for k, v in props.items():
                t = t.property(k, v)
            t.toList()
        except Exception as e:
            logger.error("Failed to update vertex props", vid=vid, error=str(e))

    def _persist_update(self, conf: UserConfirmation) -> None:
        """해결된 UserConfirmation을 그래프에 반영합니다."""
        conf_id = str(conf.id)
        update_props = {
            "status": conf.status.value,
            "user_response": conf.user_response or "",
            "resolved_at": conf.resolved_at.isoformat() if conf.resolved_at else "",
        }
        self._update_vertex_props(conf_id, update_props)

    # ── Pydantic 변환 ─────────────────────────────────────────

    @staticmethod
    def _dict_to_model(d: dict) -> UserConfirmation:
        """그래프 저장 dict → UserConfirmation Pydantic 모델 변환"""
        import json as _json

        def _parse_json(val, default):
            if isinstance(val, (list, dict)):
                return val
            if isinstance(val, str):
                try:
                    return _json.loads(val)
                except Exception:
                    return default
            return default

        try:
            source_excerpts_raw = _parse_json(d.get("source_excerpts", "[]"), [])
            excerpts = []
            for ex in source_excerpts_raw:
                if isinstance(ex, dict):
                    excerpts.append(
                        SourceExcerpt(
                            source_id=ex.get("source_id", "search"),
                            source_name=ex.get("source_name", ""),
                            source_location=ex.get("source_location", ""),
                            text=ex.get("text", ""),
                        )
                    )

            related_ids = _parse_json(d.get("related_entity_ids", "[]"), [])

            resolved_at_raw = d.get("resolved_at")
            resolved_at = None
            if resolved_at_raw:
                try:
                    resolved_at = datetime.fromisoformat(resolved_at_raw)
                except Exception:
                    pass

            return UserConfirmation(
                id=d.get("id", str(uuid.uuid4())),
                source_id=d.get("source_id", "system"),
                confirmation_type=ConfirmationType(d.get("confirmation_type", ConfirmationType.INTENTIONAL_CHANGE.value)),
                status=ConfirmationStatus(d.get("status", ConfirmationStatus.PENDING.value)),
                question=d.get("question", ""),
                context_summary=d.get("context_summary", ""),
                source_excerpts=excerpts,
                related_entity_ids=related_ids if isinstance(related_ids, list) else [],
                user_response=d.get("user_response"),
                resolved_at=resolved_at,
            )
        except Exception as e:
            logger.error("Failed to parse UserConfirmation from dict", error=str(e), raw=d)
            raise


# ─────────────────────────────────────────────────────────────
# 싱글턴 팩토리
# ─────────────────────────────────────────────────────────────

_confirmation_service: Optional[ConfirmationService] = None


def get_confirmation_service(graph_service=None) -> ConfirmationService:
    """
    ConfirmationService 싱글턴을 반환합니다.
    처음 호출 시 graph_service를 반드시 전달해야 합니다.
    """
    global _confirmation_service
    if _confirmation_service is None:
        if graph_service is None:
            raise RuntimeError(
                "graph_service must be provided on first call to get_confirmation_service()"
            )
        _confirmation_service = ConfirmationService(graph_service)
    return _confirmation_service
