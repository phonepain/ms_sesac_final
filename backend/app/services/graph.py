from typing import List, Dict, Any, Optional, Tuple
import uuid
import copy
import structlog
from collections import defaultdict
from datetime import datetime

from gremlin_python.driver import client, serializer
from gremlin_python.structure.graph import Graph
from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection
from gremlin_python.process.graph_traversal import __

from app.models.intermediate import NormalizationResult # 정규화 파이프라인의 최종 결과물 (계층 3 Graph Materialization의 입력값)
from app.models.edges import RELATIONSHIP_CONFLICT_MATRIX # 관계 모순 판별용 행렬 가이드라인 (Conflict Matrix)
from app.models.enums import (
    ConfirmationType, ConfirmationStatus, ContradictionType,
    Severity, RelationshipType,
)
from app.models.api import KBStats # Knowledge Base (KB) Status

logger = structlog.get_logger()


# ─────────────────────────────────────────────────────────────
# 유틸: Gremlin valueMap 결과에서 단일 값 추출 (list 래핑 처리)
# ─────────────────────────────────────────────────────────────

def _prop(v: Dict, key: str) -> Any:
    val = v.get(key)
    if isinstance(val, list):
        return val[0] if val else None
    return val


# ─────────────────────────────────────────────────────────────
# 공통 위반 레코드 빌더
# ─────────────────────────────────────────────────────────────

def _make_violation(
    vtype: ContradictionType,
    severity: Severity,
    description: str,
    confidence: float,
    character_id: Optional[str] = None,
    character_name: Optional[str] = None,
    evidence: Optional[List[Dict]] = None,
    needs_user_input: bool = False,
    confirmation_type: Optional[ConfirmationType] = None,
    dialogue: Optional[str] = None,
    suggestion: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "type": vtype,
        "severity": severity,
        "description": description,
        "confidence": confidence,
        "character_id": character_id,
        "character_name": character_name,
        "evidence": evidence or [],
        "needs_user_input": needs_user_input,
        "confirmation_type": confirmation_type,
        "dialogue": dialogue,
        "suggestion": suggestion,
        # Hard = confidence≥0.8 이고 사용자 확인 불필요
        "is_hard": confidence >= 0.8 and not needs_user_input,
    }


# ─────────────────────────────────────────────────────────────
# Gremlin 클라이언트 팩토리
# ─────────────────────────────────────────────────────────────

def create_gremlin_client(endpoint: str, key: str, database: str, container: str):
    url = endpoint if endpoint.startswith("wss://") else f"wss://{endpoint}:443/"
    username = f"/dbs/{database}/colls/{container}"
    graph = Graph()
    connection = DriverRemoteConnection(
        url, "g",
        username=username,
        password=key,
        message_serializer=serializer.GraphSONSerializersV2d0(),
    )
    g = graph.traversal().withRemote(connection)
    return g, connection


# ─────────────────────────────────────────────────────────────
# GremlinGraphService  (Azure Cosmos DB)
# ─────────────────────────────────────────────────────────────

class GremlinGraphService:
    """Azure Cosmos DB (Gremlin API) 기반 그래프 서비스"""

    def __init__(self, endpoint: str, key: str, database: str, container: str):
        self.endpoint = endpoint
        self.key = key
        self.database = database
        self.container = container
        self.g, self.connection = create_gremlin_client(endpoint, key, database, container)
        self._discourse_counter: float = 0.0
        logger.info("GremlinGraphService initialized")

    # ── 내부 헬퍼 ─────────────────────────────────────────────

    def _dict_to_properties(self, traversal, data: dict):
        for k, v in data.items():
            if v is not None:
                traversal = traversal.property(k, str(v) if isinstance(v, (list, dict)) else v)
        return traversal

    def _add_vertex_generic(self, label: str, data: dict, partition_key: str) -> str:
        vid = data.get("id", str(uuid.uuid4()))
        data["id"] = vid
        t = self.g.addV(label).property("id", vid).property("pk", partition_key)
        t = self._dict_to_properties(t, data)
        t.toList()
        logger.debug("Added vertex", label=label, vid=vid)
        return vid

    def _add_edge_generic(self, label: str, from_id: str, to_id: str, data: dict) -> str:
        eid = data.get("id", str(uuid.uuid4()))
        data["id"] = eid
        # from_id / to_id를 엣지 속성으로도 저장 → valueMap 조회 시 활용
        data["from_id"] = from_id
        data["to_id"] = to_id
        t = self.g.V(from_id).addE(label).to(__.V(to_id)).property("id", eid)
        t = self._dict_to_properties(t, data)
        t.toList()
        logger.debug("Added edge", label=label, from_id=from_id, to_id=to_id, eid=eid)
        return eid

    def _get_next_discourse_order(self) -> float:
        try:
            results = (
                self.g.V().hasLabel("event")
                .values("discourse_order").order().by(__.desc()).limit(1).toList()
            )
            base = float(results[0]) if results else self._discourse_counter
        except Exception:
            base = self._discourse_counter
        self._discourse_counter = round(base + 0.1, 4)
        return self._discourse_counter

    def _fetch_all(self, label: str) -> List[Dict]:
        try:
            return self.g.V().hasLabel(label).valueMap(True).toList()
        except Exception as e:
            logger.warning("Fetch failed", label=label, error=str(e))
            return []

    def _fetch_edges_by_label(self, label: str) -> List[Dict]:
        """엣지 valueMap 조회. from_id/to_id는 속성으로 저장되어 있음."""
        try:
            return self.g.E().hasLabel(label).valueMap(True).toList()
        except Exception as e:
            logger.warning("Edge fetch failed", label=label, error=str(e))
            return []

    # ── Vertex CRUD (9종) ─────────────────────────────────────

    def add_character(self, data: dict) -> str:
        return self._add_vertex_generic("character", data, "character")

    def get_character(self, char_id: str) -> Optional[Dict]:
        r = self.g.V(char_id).hasLabel("character").valueMap(True).toList()
        return r[0] if r else None

    def find_character_by_name(self, name: str) -> Optional[Dict]:
        r = self.g.V().hasLabel("character").has("name", name).valueMap(True).limit(1).toList()
        return r[0] if r else None

    def list_characters(self) -> List[Dict]:
        return self.g.V().hasLabel("character").valueMap(True).toList()

    def add_fact(self, data: dict) -> str:
        return self._add_vertex_generic("fact", data, "fact")

    def get_fact(self, fact_id: str) -> Optional[Dict]:
        r = self.g.V(fact_id).hasLabel("fact").valueMap(True).toList()
        return r[0] if r else None

    def list_facts(self) -> List[Dict]:
        return self.g.V().hasLabel("fact").valueMap(True).toList()

    def add_event(self, data: dict) -> str:
        return self._add_vertex_generic("event", data, "event")

    def get_event(self, event_id: str) -> Optional[Dict]:
        r = self.g.V(event_id).hasLabel("event").valueMap(True).toList()
        return r[0] if r else None

    def list_events(self) -> List[Dict]:
        return self.g.V().hasLabel("event").valueMap(True).toList()

    def add_trait(self, data: dict) -> str:
        return self._add_vertex_generic("trait", data, "trait")

    def get_trait(self, trait_id: str) -> Optional[Dict]:
        r = self.g.V(trait_id).hasLabel("trait").valueMap(True).toList()
        return r[0] if r else None

    def list_traits(self) -> List[Dict]:
        return self.g.V().hasLabel("trait").valueMap(True).toList()

    def add_organization(self, data: dict) -> str:
        return self._add_vertex_generic("organization", data, "organization")

    def get_organization(self, org_id: str) -> Optional[Dict]:
        r = self.g.V(org_id).hasLabel("organization").valueMap(True).toList()
        return r[0] if r else None

    def list_organizations(self) -> List[Dict]:
        return self.g.V().hasLabel("organization").valueMap(True).toList()

    def add_location(self, data: dict) -> str:
        return self._add_vertex_generic("location", data, "location")

    def get_location(self, loc_id: str) -> Optional[Dict]:
        r = self.g.V(loc_id).hasLabel("location").valueMap(True).toList()
        return r[0] if r else None

    def list_locations(self) -> List[Dict]:
        return self.g.V().hasLabel("location").valueMap(True).toList()

    def add_item(self, data: dict) -> str:
        return self._add_vertex_generic("item", data, "item")

    def get_item(self, item_id: str) -> Optional[Dict]:
        r = self.g.V(item_id).hasLabel("item").valueMap(True).toList()
        return r[0] if r else None

    def list_items(self) -> List[Dict]:
        return self.g.V().hasLabel("item").valueMap(True).toList()

    def add_source(self, data: dict) -> str:
        return self._add_vertex_generic("source", data, "source")

    def get_source(self, source_id: str) -> Optional[Dict]:
        r = self.g.V(source_id).hasLabel("source").valueMap(True).toList()
        return r[0] if r else None

    def list_sources(self) -> List[Dict]:
        return self.g.V().hasLabel("source").valueMap(True).toList()

    def add_user_confirmation(self, data: dict) -> str:
        return self._add_vertex_generic("confirmation", data, "confirmation")

    def get_user_confirmation(self, conf_id: str) -> Optional[Dict]:
        r = self.g.V(conf_id).hasLabel("confirmation").valueMap(True).toList()
        return r[0] if r else None

    def list_pending_confirmations(self) -> List[Dict]:
        return (
            self.g.V().hasLabel("confirmation")
            .has("status", ConfirmationStatus.PENDING.value)
            .valueMap(True).toList()
        )

    # ── Edge 추가 (13종) ──────────────────────────────────────

    def add_learns(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("LEARNS", from_id, to_id, data)

    def add_mentions(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("MENTIONS", from_id, to_id, data)

    def add_participates_in(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("PARTICIPATES_IN", from_id, to_id, data)

    def add_has_status(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("HAS_STATUS", from_id, to_id, data)

    def add_at_location(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("AT_LOCATION", from_id, to_id, data)

    def add_related_to(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("RELATED_TO", from_id, to_id, data)

    def add_belongs_to(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("BELONGS_TO", from_id, to_id, data)

    def add_feels(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("FEELS", from_id, to_id, data)

    def add_has_trait(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("HAS_TRAIT", from_id, to_id, data)

    def add_violates_trait(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("VIOLATES_TRAIT", from_id, to_id, data)

    def add_possesses(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("POSSESSES", from_id, to_id, data)

    def add_loses(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("LOSES", from_id, to_id, data)

    def add_sourced_from(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("SOURCED_FROM", from_id, to_id, data)

    # ── 계층 3: Graph 적재 ────────────────────────────────────

    def materialize(self, normalized: NormalizationResult, source: Any) -> Dict[str, List[str]]:
        """NormalizationResult → Cosmos DB Graph 적재"""
        source_id = str(getattr(source, "id", source))
        now = datetime.now().isoformat()
        created: Dict[str, List[str]] = {"characters": [], "facts": [], "confirmations": []}

        logger.info("Materializing NormalizationResult", source_id=source_id)
        try:
            # 1. Character vertices
            for nc in normalized.characters:
                char_id = str(uuid.uuid4())
                self.add_character({
                    "id": char_id,
                    "name": nc.canonical_name,
                    "aliases": str(nc.all_aliases),
                    "tier": nc.tier,
                    "description": nc.description or "",
                    "source_id": source_id,
                    "partition_key": "character",
                    "created_at": now,
                })
                self.add_sourced_from(char_id, source_id, {
                    "source_id": source_id, "source_location": "", "created_at": now,
                })
                created["characters"].append(char_id)

            # 2. KnowledgeFact vertices (discourse_order 자동 부여)
            for nf in normalized.facts:
                do = self._get_next_discourse_order()
                fact_id = str(uuid.uuid4())
                self.add_fact({
                    "id": fact_id,
                    "content": nf.content,
                    "category": nf.category,
                    "importance": nf.importance,
                    "is_secret": nf.is_secret,
                    "is_true": nf.is_true,
                    "established_order": do,
                    "source_location": "",
                    "source_id": source_id,
                    "partition_key": "fact",
                    "created_at": now,
                })
                self.add_sourced_from(fact_id, source_id, {
                    "source_id": source_id, "source_location": "", "created_at": now,
                })
                created["facts"].append(fact_id)

            # 3. SourceConflict → UserConfirmation vertices
            for conflict in normalized.source_conflicts:
                conf_id = str(uuid.uuid4())
                excerpts = "; ".join(
                    f"[{d.source_id}] {d.text}" for d in conflict.descriptions
                )
                self.add_user_confirmation({
                    "id": conf_id,
                    "confirmation_type": ConfirmationType.SOURCE_CONFLICT.value,
                    "status": ConfirmationStatus.PENDING.value,
                    "question": (
                        f"소스 충돌: '{conflict.entity_type}'에 대해 "
                        f"소스들이 서로 다른 내용을 기술합니다. 어느 것이 정본입니까?"
                    ),
                    "context_summary": f"충돌 값: {', '.join(conflict.conflicting_values)}",
                    "source_excerpts": excerpts,
                    "related_entity_ids": "",
                    "source_id": source_id,
                    "partition_key": "confirmation",
                    "created_at": now,
                })
                created["confirmations"].append(conf_id)

            logger.info("Materialization complete", **{k: len(v) for k, v in created.items()})
            return created

        except Exception as e:
            logger.error("Materialization failed", error=str(e))
            raise

    def _assign_time_axes(self, events: List[Dict]) -> List[Dict]:
        """discourse_order 단조 증가 보장 + 비선형 힌트 기반 story_order 추정"""
        TIME_JUMP_HINTS = [
            "전", "후", "년 전", "일 전", "며칠 후", "그날 밤",
            "그때", "과거에", "회상", "flashback", "그 무렵",
        ]
        result = []
        counter = 0.0
        for ev in events:
            counter = round(counter + 0.1, 4)
            ev["discourse_order"] = counter
            desc = str(ev.get("description", ""))
            if any(hint in desc for hint in TIME_JUMP_HINTS):
                ev["is_linear"] = False
                ev["story_order"] = None  # 미확정 → 사용자 확인 대상
            else:
                ev["is_linear"] = True
                ev["story_order"] = ev["discourse_order"]
            result.append(ev)
        return result

    # ── 7가지 모순 탐지 쿼리 ──────────────────────────────────

    def find_knowledge_violations(self) -> List[Dict[str, Any]]:
        """1. 정보 비대칭: MENTIONS.story_order < LEARNS.story_order"""
        violations = []
        mentions = self._fetch_edges_by_label("MENTIONS")
        learns = self._fetch_edges_by_label("LEARNS")

        # (char_id, fact_id) → 최초 LEARNS story_order
        learn_index: Dict[Tuple[str, str], float] = {}
        for e in learns:
            cid, fid, so = _prop(e, "from_id"), _prop(e, "to_id"), _prop(e, "story_order")
            if cid and fid and so is not None:
                key = (cid, fid)
                if key not in learn_index or float(so) < learn_index[key]:
                    learn_index[key] = float(so)

        for e in mentions:
            cid, fid, m_so = _prop(e, "from_id"), _prop(e, "to_id"), _prop(e, "story_order")
            if not (cid and fid and m_so is not None):
                continue
            m_so = float(m_so)
            l_so = learn_index.get((cid, fid))
            if l_so is not None and m_so < l_so:
                violations.append(_make_violation(
                    vtype=ContradictionType.ASYMMETRY,
                    severity=Severity.CRITICAL,
                    description=(
                        f"캐릭터({cid})가 사실({fid})을 알기 전(LEARNS story_order={l_so}) "
                        f"이미 언급(MENTIONS story_order={m_so})"
                    ),
                    confidence=0.95,
                    character_id=cid,
                    evidence=[
                        {"type": "MENTIONS", "story_order": m_so, "dialogue": _prop(e, "dialogue_text")},
                        {"type": "LEARNS", "story_order": l_so},
                    ],
                    suggestion="MENTIONS 시점을 LEARNS 이후로 수정하거나, LEARNS 시점을 앞당기세요.",
                ))
        return violations

    def find_timeline_violations(self) -> List[Dict[str, Any]]:
        """2. 타임라인: 사망 후 재등장, 동시 다중 위치"""
        violations = []
        has_status = self._fetch_edges_by_label("HAS_STATUS")
        at_location = self._fetch_edges_by_label("AT_LOCATION")

        # 사망 인덱스: char_id → death story_order
        death_index: Dict[str, float] = {}
        for e in has_status:
            if _prop(e, "status_type") == "dead":
                cid, so = _prop(e, "from_id"), _prop(e, "story_order")
                if cid and so is not None:
                    death_index[cid] = float(so)

        # 사망 후 위치 이동 체크
        for e in at_location:
            cid, so = _prop(e, "from_id"), _prop(e, "story_order")
            if not (cid and so is not None):
                continue
            so = float(so)
            death_so = death_index.get(cid)
            if death_so is not None and so > death_so:
                violations.append(_make_violation(
                    vtype=ContradictionType.TIMELINE,
                    severity=Severity.CRITICAL,
                    description=f"캐릭터({cid})가 사망(story_order={death_so}) 후 위치 이동(story_order={so})",
                    confidence=0.95,
                    character_id=cid,
                    evidence=[{"death_at": death_so, "appears_at": so}],
                    suggestion="사망 이벤트 또는 이후 등장 시점을 수정하세요.",
                ))

        # 동시 다중 위치 체크
        time_char_locs: Dict[Tuple[str, float], List[str]] = defaultdict(list)
        for e in at_location:
            cid, so, loc = _prop(e, "from_id"), _prop(e, "story_order"), _prop(e, "to_id")
            if cid and so is not None and loc:
                time_char_locs[(cid, float(so))].append(loc)
        for (cid, so), locs in time_char_locs.items():
            if len(set(locs)) > 1:
                violations.append(_make_violation(
                    vtype=ContradictionType.TIMELINE,
                    severity=Severity.CRITICAL,
                    description=f"캐릭터({cid})가 story_order={so}에 동시에 {len(locs)}개 장소 존재",
                    confidence=0.98,
                    character_id=cid,
                    evidence=[{"locations": locs, "story_order": so}],
                    suggestion="동시 위치 중 하나의 story_order를 조정하세요.",
                ))
        return violations

    def find_relationship_violations(self) -> List[Dict[str, Any]]:
        """3. 관계 모순: RELATIONSHIP_CONFLICT_MATRIX 기반"""
        violations = []
        related = self._fetch_edges_by_label("RELATED_TO")
        pair_index: Dict[frozenset, List[str]] = {}
        for e in related:
            a, b, rtype = _prop(e, "from_id"), _prop(e, "to_id"), _prop(e, "relationship_type")
            if a and b and rtype:
                pair_index.setdefault(frozenset([a, b]), []).append(rtype)

        for pair, rtypes in pair_index.items():
            pair_list = list(pair)
            for i, rt1 in enumerate(rtypes):
                for rt2 in rtypes[i + 1:]:
                    try:
                        r1, r2 = RelationshipType(rt1), RelationshipType(rt2)
                    except ValueError:
                        continue
                    level = RELATIONSHIP_CONFLICT_MATRIX.get(frozenset([r1, r2]))
                    if level == "critical":
                        violations.append(_make_violation(
                            vtype=ContradictionType.RELATIONSHIP,
                            severity=Severity.CRITICAL,
                            description=f"캐릭터 쌍({pair_list})의 관계 모순: {rt1} ↔ {rt2}",
                            confidence=0.95,
                            evidence=[{"pair": pair_list, "relationship_types": rtypes}],
                            suggestion=f"관계 유형 '{rt1}'과 '{rt2}' 중 하나를 수정하세요.",
                        ))
                    elif level == "warning":
                        violations.append(_make_violation(
                            vtype=ContradictionType.RELATIONSHIP,
                            severity=Severity.MAJOR,
                            description=f"캐릭터 쌍({pair_list})의 관계 경고: {rt1} ↔ {rt2}",
                            confidence=0.6,
                            evidence=[{"pair": pair_list, "relationship_types": rtypes}],
                            needs_user_input=True,
                            confirmation_type=ConfirmationType.RELATIONSHIP_AMBIGUITY,
                        ))
        return violations

    def find_trait_violations(self) -> List[Dict[str, Any]]:
        """4. 성격·설정 모순: 같은 key 다른 value"""
        violations = []
        has_trait = self._fetch_edges_by_label("HAS_TRAIT")
        traits = {_prop(v, "id"): v for v in self._fetch_all("trait")}

        char_trait_index: Dict[Tuple[str, str], List[Dict]] = {}
        for e in has_trait:
            cid, tid = _prop(e, "from_id"), _prop(e, "to_id")
            trait = traits.get(tid, {})
            key, val = _prop(trait, "key"), _prop(trait, "value")
            immutable = _prop(trait, "is_immutable") in (True, "True", "true", 1)
            if cid and key:
                char_trait_index.setdefault((cid, key), []).append(
                    {"value": val, "is_immutable": immutable}
                )

        for (cid, trait_key), entries in char_trait_index.items():
            values = [e["value"] for e in entries]
            if len(set(str(v) for v in values)) > 1:
                is_imm = any(e["is_immutable"] for e in entries)
                violations.append(_make_violation(
                    vtype=ContradictionType.TRAIT,
                    severity=Severity.CRITICAL if is_imm else Severity.MAJOR,
                    description=f"캐릭터({cid})의 특성 '{trait_key}'에 상충 값: {values}",
                    confidence=0.95 if is_imm else 0.6,
                    character_id=cid,
                    evidence=[{"trait_key": trait_key, "values": values}],
                    needs_user_input=not is_imm,
                    confirmation_type=ConfirmationType.INTENTIONAL_CHANGE if not is_imm else None,
                    suggestion=f"'{trait_key}' 특성 값을 통일하거나 변화 이유를 명시하세요.",
                ))
        return violations

    def find_emotion_violations(self) -> List[Dict[str, Any]]:
        """5. 감정 일관성: trigger 없는 반대 감정으로의 급변"""
        violations = []
        feels = self._fetch_edges_by_label("FEELS")
        pair_emotions: Dict[Tuple[str, str], List[Dict]] = {}
        for e in feels:
            fid, tid = _prop(e, "from_id"), _prop(e, "to_id")
            if fid and tid:
                pair_emotions.setdefault((fid, tid), []).append(e)

        OPPOSITES = {
            frozenset(["love", "hate"]),
            frozenset(["trust", "distrust"]),
            frozenset(["admiration", "contempt"]),
            frozenset(["gratitude", "resentment"]),
        }
        for (fid, tid), history in pair_emotions.items():
            sorted_h = sorted(history, key=lambda x: float(_prop(x, "discourse_order") or 0))
            for i in range(1, len(sorted_h)):
                prev, curr = sorted_h[i - 1], sorted_h[i]
                pair = frozenset([str(_prop(prev, "emotion")), str(_prop(curr, "emotion"))])
                if pair in OPPOSITES and not _prop(curr, "trigger_event_id"):
                    violations.append(_make_violation(
                        vtype=ContradictionType.EMOTION,
                        severity=Severity.MAJOR,
                        description=(
                            f"캐릭터({fid})의 감정이 트리거 없이 "
                            f"{_prop(prev, 'emotion')} → {_prop(curr, 'emotion')} 급변"
                        ),
                        confidence=0.6,
                        character_id=fid,
                        evidence=[{"prev": _prop(prev, "emotion"), "curr": _prop(curr, "emotion")}],
                        needs_user_input=True,
                        confirmation_type=ConfirmationType.EMOTION_SHIFT,
                        suggestion="감정 변화를 유발한 이벤트를 명시하거나 감정 추이를 자연스럽게 조정하세요.",
                    ))
        return violations

    def find_item_violations(self) -> List[Dict[str, Any]]:
        """6. 소유물 추적: 동시 이중 소유, 분실 후 재소유"""
        violations = []
        possesses = self._fetch_edges_by_label("POSSESSES")
        loses = self._fetch_edges_by_label("LOSES")

        item_history: Dict[str, List[Dict]] = {}
        for e in possesses:
            iid = _prop(e, "to_id")
            if iid:
                item_history.setdefault(iid, []).append({
                    "type": "possesses", "char_id": _prop(e, "from_id"),
                    "story_order": _prop(e, "story_order"),
                })
        for e in loses:
            iid = _prop(e, "to_id")
            if iid:
                item_history.setdefault(iid, []).append({
                    "type": "loses", "char_id": _prop(e, "from_id"),
                    "story_order": _prop(e, "story_order"),
                })

        for item_id, history in item_history.items():
            sorted_h = [h for h in history if h.get("story_order") is not None]
            sorted_h.sort(key=lambda x: float(x["story_order"]))

            # 동시 이중 소유
            time_owners: Dict[float, List[str]] = defaultdict(list)
            for h in sorted_h:
                if h["type"] == "possesses":
                    time_owners[float(h["story_order"])].append(h["char_id"])
            for so, owners in time_owners.items():
                if len(set(owners)) > 1:
                    violations.append(_make_violation(
                        vtype=ContradictionType.ITEM,
                        severity=Severity.CRITICAL,
                        description=f"아이템({item_id})이 story_order={so}에 {len(owners)}명에게 동시 소유",
                        confidence=0.95,
                        evidence=[{"item_id": item_id, "story_order": so, "owners": owners}],
                        suggestion="동시 소유 중 하나의 story_order를 조정하거나 소유권 이전을 추가하세요.",
                    ))

            # 분실 후 재소유
            last_loses: Dict[str, float] = {}
            for h in sorted_h:
                if h["type"] == "loses":
                    last_loses[h["char_id"]] = float(h["story_order"])
                elif h["type"] == "possesses":
                    cid, so = h["char_id"], float(h["story_order"])
                    lost_at = last_loses.get(cid)
                    if lost_at is not None and so > lost_at:
                        violations.append(_make_violation(
                            vtype=ContradictionType.ITEM,
                            severity=Severity.MAJOR,
                            description=(
                                f"캐릭터({cid})가 아이템({item_id}) 분실(story_order={lost_at}) "
                                f"후 재소유(story_order={so})"
                            ),
                            confidence=0.65,
                            character_id=cid,
                            evidence=[{"lost_at": lost_at, "repossessed_at": so}],
                            needs_user_input=True,
                            confirmation_type=ConfirmationType.ITEM_DISCREPANCY,
                        ))
        return violations

    def find_deception_violations(self) -> List[Dict[str, Any]]:
        """7. 거짓말·기만: is_true=False 사실 학습(believed_true=True), 진실 인지 후 거짓 발언"""
        violations = []
        facts = {_prop(v, "id"): v for v in self._fetch_all("fact")}
        learns = self._fetch_edges_by_label("LEARNS")
        mentions = self._fetch_edges_by_label("MENTIONS")

        false_fact_ids = {
            fid for fid, fv in facts.items()
            if _prop(fv, "is_true") in (False, "False", "false", 0)
        }

        # 거짓 사실을 진실로 학습한 (char, fact) → story_order
        believed_false: Dict[Tuple[str, str], float] = {}
        for e in learns:
            fid, cid = _prop(e, "to_id"), _prop(e, "from_id")
            believed = _prop(e, "believed_true")
            so = _prop(e, "story_order")
            if fid in false_fact_ids and believed in (True, "True", "true", 1):
                if cid and so is not None:
                    believed_false[(cid, fid)] = float(so)

        # 진실 학습 최소 story_order: (char, fact) → story_order
        truth_learn: Dict[Tuple[str, str], float] = {}
        for e in learns:
            fid, cid = _prop(e, "to_id"), _prop(e, "from_id")
            believed = _prop(e, "believed_true")
            so = _prop(e, "story_order")
            if fid not in false_fact_ids and believed in (True, "True", "true", 1):
                if cid and so is not None:
                    key = (cid, fid)
                    if key not in truth_learn or float(so) < truth_learn[key]:
                        truth_learn[key] = float(so)

        # 진실 인지 후 거짓 사실을 언급한 경우
        for e in mentions:
            cid, fid, so = _prop(e, "from_id"), _prop(e, "to_id"), _prop(e, "story_order")
            if not (cid and fid and so is not None and fid in false_fact_ids):
                continue
            so = float(so)
            truth_so = truth_learn.get((cid, fid))
            if truth_so is not None and so > truth_so:
                violations.append(_make_violation(
                    vtype=ContradictionType.DECEPTION,
                    severity=Severity.CRITICAL,
                    description=(
                        f"캐릭터({cid})가 진실 인지(story_order={truth_so}) 후에도 "
                        f"거짓 사실({fid})을 언급(story_order={so})"
                    ),
                    confidence=0.9,
                    character_id=cid,
                    dialogue=_prop(e, "dialogue_text"),
                    evidence=[{"truth_learned_at": truth_so, "false_mention_at": so}],
                    suggestion="진실 인지 후 거짓 정보 전달의 의도를 명시하거나 제거하세요.",
                ))

        # 거짓 사실을 believed_true=True로 학습한 케이스 자체 (Soft)
        for (cid, fid), so in believed_false.items():
            violations.append(_make_violation(
                vtype=ContradictionType.DECEPTION,
                severity=Severity.MINOR,
                description=f"캐릭터({cid})가 거짓 사실({fid})을 진실로 학습(story_order={so})",
                confidence=0.55,
                character_id=cid,
                evidence=[{"fact_id": fid, "believed_true_at": so}],
                needs_user_input=True,
                confirmation_type=ConfirmationType.UNRELIABLE_NARRATOR,
            ))
        return violations

    def find_all_violations(self) -> Dict[str, List[Dict[str, Any]]]:
        """7가지 쿼리 통합 + Hard / Soft 분류"""
        all_v = (
            self.find_knowledge_violations()
            + self.find_timeline_violations()
            + self.find_relationship_violations()
            + self.find_trait_violations()
            + self.find_emotion_violations()
            + self.find_item_violations()
            + self.find_deception_violations()
        )
        hard = [v for v in all_v if v.get("is_hard")]
        soft = [v for v in all_v if not v.get("is_hard")]
        logger.info("find_all_violations complete", hard=len(hard), soft=len(soft), total=len(all_v))
        return {"hard": hard, "soft": soft, "all": all_v}

    # ── 임시 그래프 격리 ──────────────────────────────────────

    def snapshot_graph(self, relevant_ids: Optional[List[str]] = None) -> "InMemoryGraphService":
        """canonical graph의 서브그래프를 InMemory로 복제. 원본 불변 보장."""
        mem = InMemoryGraphService()
        try:
            EDGE_LABELS = [
                "LEARNS", "MENTIONS", "PARTICIPATES_IN", "HAS_STATUS",
                "AT_LOCATION", "RELATED_TO", "BELONGS_TO", "FEELS",
                "HAS_TRAIT", "VIOLATES_TRAIT", "POSSESSES", "LOSES", "SOURCED_FROM",
            ]
            if relevant_ids:
                for vid in relevant_ids:
                    try:
                        res = self.g.V(vid).valueMap(True).toList()
                        if res:
                            v = res[0]
                            v_id = _prop(v, "id") or vid
                            mem.vertices[v_id] = {"label": _prop(v, "label") or "unknown", **{k: _prop(v, k) for k in v}}
                    except Exception:
                        pass
                id_set = set(relevant_ids)
                for lbl in EDGE_LABELS:
                    try:
                        edges = self.g.V(relevant_ids).bothE(lbl).valueMap(True).toList()
                        for e in edges:
                            eid = _prop(e, "id") or str(uuid.uuid4())
                            mem.edges.append({"id": eid, "label": lbl, **{k: _prop(e, k) for k in e}})
                    except Exception:
                        pass
            else:
                for v in self.g.V().valueMap(True).toList():
                    v_id = _prop(v, "id") or str(uuid.uuid4())
                    mem.vertices[v_id] = {"label": _prop(v, "label") or "unknown", **{k: _prop(v, k) for k in v}}
                for lbl in EDGE_LABELS:
                    for e in self._fetch_edges_by_label(lbl):
                        eid = _prop(e, "id") or str(uuid.uuid4())
                        mem.edges.append({"id": eid, "label": lbl, **{k: _prop(e, k) for k in e}})

            logger.info("snapshot_graph complete", vertices=len(mem.vertices), edges=len(mem.edges))
        except Exception as e:
            logger.error("snapshot_graph failed", error=str(e))
        return mem

    # ── 유틸리티 ──────────────────────────────────────────────

    def get_character_knowledge_at(self, character_id: str, story_order: float) -> List[Dict]:
        """특정 story_order 시점까지 캐릭터가 학습한 사실 목록"""
        try:
            learns = self.g.V(character_id).outE("LEARNS").valueMap(True).toList()
            return [
                e for e in learns
                if _prop(e, "story_order") is not None
                and float(_prop(e, "story_order")) <= story_order
            ]
        except Exception:
            return []

    def get_stats(self) -> KBStats:
        def count_v(label: str) -> int:
            try:
                return self.g.V().hasLabel(label).count().next()
            except Exception:
                return 0

        def count_e(label: str) -> int:
            try:
                return self.g.E().hasLabel(label).count().next()
            except Exception:
                return 0

        return KBStats(
            characters=count_v("character"),
            facts=count_v("fact"),
            relationships=count_e("RELATED_TO"),
            events=count_v("event"),
            traits=count_v("trait"),
            locations=count_v("location"),
            items=count_v("item"),
            organizations=count_v("organization"),
            sources=count_v("source"),
            confirmations=count_v("confirmation"),
        )

    def remove_source(self, source_id: str) -> Dict[str, int]:
        """소스 및 연관 vertex/edge 전체 삭제"""
        removed = {"vertices": 0, "edges": 0}
        try:
            e_cnt = self.g.E().has("source_id", source_id).count().next()
            self.g.E().has("source_id", source_id).drop().iterate()
            removed["edges"] = e_cnt

            v_cnt = self.g.V().has("source_id", source_id).count().next()
            self.g.V().has("source_id", source_id).drop().iterate()
            removed["vertices"] = v_cnt

            logger.info("remove_source complete", source_id=source_id, **removed)
        except Exception as e:
            logger.error("remove_source failed", source_id=source_id, error=str(e))
            raise
        return removed

    def close(self):
        self.connection.close()


# ─────────────────────────────────────────────────────────────
# InMemoryGraphService  (테스트 / 로컬 개발)
# ─────────────────────────────────────────────────────────────

class InMemoryGraphService:
    """GremlinGraphService와 동일 인터페이스의 In-Memory 구현체."""

    def __init__(self):
        self.vertices: Dict[str, Dict[str, Any]] = {}
        self.edges: List[Dict[str, Any]] = []
        self._discourse_counter: float = 0.0

    # ── 내부 헬퍼 ─────────────────────────────────────────────

    def _add_vertex(self, label: str, data: dict) -> str:
        vid = data.get("id", str(uuid.uuid4()))
        self.vertices[vid] = {"label": label, "id": vid, **data}
        return vid

    def _add_edge(self, label: str, from_id: str, to_id: str, data: dict) -> str:
        eid = data.get("id", str(uuid.uuid4()))
        self.edges.append({"label": label, "id": eid, "from_id": from_id, "to_id": to_id, **data})
        return eid

    def _vertices_by_label(self, label: str) -> List[Dict]:
        return [v for v in self.vertices.values() if v.get("label") == label]

    def _edges_by_label(self, label: str) -> List[Dict]:
        return [e for e in self.edges if e.get("label") == label]

    def _get_next_discourse_order(self) -> float:
        self._discourse_counter = round(self._discourse_counter + 0.1, 4)
        return self._discourse_counter

    # ── Vertex CRUD (9종) ─────────────────────────────────────

    def add_character(self, data: dict) -> str:
        return self._add_vertex("character", data)

    def get_character(self, char_id: str) -> Optional[Dict]:
        v = self.vertices.get(char_id)
        return v if v and v.get("label") == "character" else None

    def find_character_by_name(self, name: str) -> Optional[Dict]:
        return next((v for v in self._vertices_by_label("character") if v.get("name") == name), None)

    def list_characters(self) -> List[Dict]:
        return self._vertices_by_label("character")

    def add_fact(self, data: dict) -> str:
        return self._add_vertex("fact", data)

    def get_fact(self, fact_id: str) -> Optional[Dict]:
        v = self.vertices.get(fact_id)
        return v if v and v.get("label") == "fact" else None

    def list_facts(self) -> List[Dict]:
        return self._vertices_by_label("fact")

    def add_event(self, data: dict) -> str:
        return self._add_vertex("event", data)

    def get_event(self, event_id: str) -> Optional[Dict]:
        v = self.vertices.get(event_id)
        return v if v and v.get("label") == "event" else None

    def list_events(self) -> List[Dict]:
        return self._vertices_by_label("event")

    def add_trait(self, data: dict) -> str:
        return self._add_vertex("trait", data)

    def get_trait(self, trait_id: str) -> Optional[Dict]:
        v = self.vertices.get(trait_id)
        return v if v and v.get("label") == "trait" else None

    def list_traits(self) -> List[Dict]:
        return self._vertices_by_label("trait")

    def add_organization(self, data: dict) -> str:
        return self._add_vertex("organization", data)

    def get_organization(self, org_id: str) -> Optional[Dict]:
        v = self.vertices.get(org_id)
        return v if v and v.get("label") == "organization" else None

    def list_organizations(self) -> List[Dict]:
        return self._vertices_by_label("organization")

    def add_location(self, data: dict) -> str:
        return self._add_vertex("location", data)

    def get_location(self, loc_id: str) -> Optional[Dict]:
        v = self.vertices.get(loc_id)
        return v if v and v.get("label") == "location" else None

    def list_locations(self) -> List[Dict]:
        return self._vertices_by_label("location")

    def add_item(self, data: dict) -> str:
        return self._add_vertex("item", data)

    def get_item(self, item_id: str) -> Optional[Dict]:
        v = self.vertices.get(item_id)
        return v if v and v.get("label") == "item" else None

    def list_items(self) -> List[Dict]:
        return self._vertices_by_label("item")

    def add_source(self, data: dict) -> str:
        return self._add_vertex("source", data)

    def get_source(self, source_id: str) -> Optional[Dict]:
        v = self.vertices.get(source_id)
        return v if v and v.get("label") == "source" else None

    def list_sources(self) -> List[Dict]:
        return self._vertices_by_label("source")

    def add_user_confirmation(self, data: dict) -> str:
        return self._add_vertex("confirmation", data)

    def get_user_confirmation(self, conf_id: str) -> Optional[Dict]:
        v = self.vertices.get(conf_id)
        return v if v and v.get("label") == "confirmation" else None

    def list_pending_confirmations(self) -> List[Dict]:
        return [
            v for v in self._vertices_by_label("confirmation")
            if v.get("status") == ConfirmationStatus.PENDING.value
        ]

    # ── Edge 추가 (13종) ──────────────────────────────────────

    def add_learns(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge("LEARNS", from_id, to_id, data)

    def add_mentions(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge("MENTIONS", from_id, to_id, data)

    def add_participates_in(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge("PARTICIPATES_IN", from_id, to_id, data)

    def add_has_status(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge("HAS_STATUS", from_id, to_id, data)

    def add_at_location(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge("AT_LOCATION", from_id, to_id, data)

    def add_related_to(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge("RELATED_TO", from_id, to_id, data)

    def add_belongs_to(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge("BELONGS_TO", from_id, to_id, data)

    def add_feels(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge("FEELS", from_id, to_id, data)

    def add_has_trait(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge("HAS_TRAIT", from_id, to_id, data)

    def add_violates_trait(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge("VIOLATES_TRAIT", from_id, to_id, data)

    def add_possesses(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge("POSSESSES", from_id, to_id, data)

    def add_loses(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge("LOSES", from_id, to_id, data)

    def add_sourced_from(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge("SOURCED_FROM", from_id, to_id, data)

    # ── 계층 3: 적재 ──────────────────────────────────────────

    def materialize(self, normalized: NormalizationResult, source: Any) -> Dict[str, List[str]]:
        source_id = str(getattr(source, "id", source))
        now = datetime.now().isoformat()
        created: Dict[str, List[str]] = {"characters": [], "facts": [], "confirmations": []}

        for nc in normalized.characters:
            char_id = str(uuid.uuid4())
            self.add_character({
                "id": char_id, "name": nc.canonical_name,
                "aliases": str(nc.all_aliases), "tier": nc.tier,
                "description": nc.description or "", "source_id": source_id, "created_at": now,
            })
            self.add_sourced_from(char_id, source_id, {"source_id": source_id, "source_location": ""})
            created["characters"].append(char_id)

        for nf in normalized.facts:
            do = self._get_next_discourse_order()
            fact_id = str(uuid.uuid4())
            self.add_fact({
                "id": fact_id, "content": nf.content, "category": nf.category,
                "importance": nf.importance, "is_secret": nf.is_secret, "is_true": nf.is_true,
                "established_order": do, "source_location": "", "source_id": source_id, "created_at": now,
            })
            self.add_sourced_from(fact_id, source_id, {"source_id": source_id, "source_location": ""})
            created["facts"].append(fact_id)

        for conflict in normalized.source_conflicts:
            conf_id = str(uuid.uuid4())
            excerpts = "; ".join(f"[{d.source_id}] {d.text}" for d in conflict.descriptions)
            self.add_user_confirmation({
                "id": conf_id,
                "confirmation_type": ConfirmationType.SOURCE_CONFLICT.value,
                "status": ConfirmationStatus.PENDING.value,
                "question": f"소스 충돌: '{conflict.entity_type}'의 정본을 선택하세요.",
                "context_summary": f"충돌 값: {', '.join(conflict.conflicting_values)}",
                "source_excerpts": excerpts, "related_entity_ids": "",
                "source_id": source_id, "created_at": now,
            })
            created["confirmations"].append(conf_id)

        return created

    # ── 7가지 모순 탐지 쿼리 ──────────────────────────────────

    def find_knowledge_violations(self) -> List[Dict[str, Any]]:
        """1. 정보 비대칭"""
        violations = []
        mentions = self._edges_by_label("MENTIONS")
        learns = self._edges_by_label("LEARNS")

        learn_index: Dict[Tuple[str, str], float] = {}
        for e in learns:
            cid, fid, so = e.get("from_id"), e.get("to_id"), e.get("story_order")
            if cid and fid and so is not None:
                key = (cid, fid)
                if key not in learn_index or float(so) < learn_index[key]:
                    learn_index[key] = float(so)

        for e in mentions:
            cid, fid, m_so = e.get("from_id"), e.get("to_id"), e.get("story_order")
            if not (cid and fid and m_so is not None):
                continue
            m_so = float(m_so)
            l_so = learn_index.get((cid, fid))
            if l_so is not None and m_so < l_so:
                char_name = (self.get_character(cid) or {}).get("name", cid)
                violations.append(_make_violation(
                    vtype=ContradictionType.ASYMMETRY,
                    severity=Severity.CRITICAL,
                    description=(
                        f"캐릭터 '{char_name}'이(가) 사실을 알기 전(LEARNS story_order={l_so}) "
                        f"이미 언급(MENTIONS story_order={m_so})"
                    ),
                    confidence=0.95,
                    character_id=cid, character_name=char_name,
                    evidence=[
                        {"type": "MENTIONS", "story_order": m_so, "dialogue": e.get("dialogue_text")},
                        {"type": "LEARNS", "story_order": l_so},
                    ],
                    suggestion="MENTIONS 시점을 LEARNS 이후로 수정하거나 LEARNS 시점을 앞당기세요.",
                ))
        return violations

    def find_timeline_violations(self) -> List[Dict[str, Any]]:
        """2. 타임라인"""
        violations = []
        has_status = self._edges_by_label("HAS_STATUS")
        at_location = self._edges_by_label("AT_LOCATION")

        death_index: Dict[str, float] = {}
        for e in has_status:
            if e.get("status_type") == "dead":
                cid, so = e.get("from_id"), e.get("story_order")
                if cid and so is not None:
                    death_index[cid] = float(so)

        for e in at_location:
            cid, so = e.get("from_id"), e.get("story_order")
            if not (cid and so is not None):
                continue
            so = float(so)
            death_so = death_index.get(cid)
            if death_so is not None and so > death_so:
                char_name = (self.get_character(cid) or {}).get("name", cid)
                violations.append(_make_violation(
                    vtype=ContradictionType.TIMELINE,
                    severity=Severity.CRITICAL,
                    description=f"캐릭터 '{char_name}'이(가) 사망(story_order={death_so}) 후 위치 이동(story_order={so})",
                    confidence=0.95,
                    character_id=cid, character_name=char_name,
                    evidence=[{"death_at": death_so, "appears_at": so}],
                    suggestion="사망 이벤트 또는 이후 등장 시점을 수정하세요.",
                ))

        time_char_locs: Dict[Tuple[str, float], List[str]] = defaultdict(list)
        for e in at_location:
            cid, so, loc = e.get("from_id"), e.get("story_order"), e.get("to_id")
            if cid and so is not None and loc:
                time_char_locs[(cid, float(so))].append(loc)
        for (cid, so), locs in time_char_locs.items():
            if len(set(locs)) > 1:
                char_name = (self.get_character(cid) or {}).get("name", cid)
                violations.append(_make_violation(
                    vtype=ContradictionType.TIMELINE,
                    severity=Severity.CRITICAL,
                    description=f"캐릭터 '{char_name}'이(가) story_order={so}에 동시에 {len(locs)}개 장소 존재",
                    confidence=0.98,
                    character_id=cid, character_name=char_name,
                    evidence=[{"locations": locs, "story_order": so}],
                    suggestion="동시 위치 중 하나의 story_order를 조정하세요.",
                ))
        return violations

    def find_relationship_violations(self) -> List[Dict[str, Any]]:
        """3. 관계 모순"""
        violations = []
        related = self._edges_by_label("RELATED_TO")
        pair_index: Dict[frozenset, List[str]] = {}
        for e in related:
            a, b, rtype = e.get("from_id"), e.get("to_id"), e.get("relationship_type")
            if a and b and rtype:
                pair_index.setdefault(frozenset([a, b]), []).append(rtype)

        for pair, rtypes in pair_index.items():
            pair_list = list(pair)
            for i, rt1 in enumerate(rtypes):
                for rt2 in rtypes[i + 1:]:
                    try:
                        r1, r2 = RelationshipType(rt1), RelationshipType(rt2)
                    except ValueError:
                        continue
                    level = RELATIONSHIP_CONFLICT_MATRIX.get(frozenset([r1, r2]))
                    if level == "critical":
                        violations.append(_make_violation(
                            vtype=ContradictionType.RELATIONSHIP,
                            severity=Severity.CRITICAL,
                            description=f"캐릭터 쌍의 관계 모순: {rt1} ↔ {rt2}",
                            confidence=0.95,
                            evidence=[{"pair": pair_list, "relationship_types": rtypes}],
                            suggestion=f"관계 '{rt1}'과 '{rt2}' 중 하나를 수정하세요.",
                        ))
                    elif level == "warning":
                        violations.append(_make_violation(
                            vtype=ContradictionType.RELATIONSHIP,
                            severity=Severity.MAJOR,
                            description=f"캐릭터 쌍의 관계 경고: {rt1} ↔ {rt2}",
                            confidence=0.6,
                            evidence=[{"pair": pair_list, "relationship_types": rtypes}],
                            needs_user_input=True,
                            confirmation_type=ConfirmationType.RELATIONSHIP_AMBIGUITY,
                        ))
        return violations

    def find_trait_violations(self) -> List[Dict[str, Any]]:
        """4. 성격·설정 모순"""
        violations = []
        has_trait = self._edges_by_label("HAS_TRAIT")
        char_trait_index: Dict[Tuple[str, str], List[Dict]] = {}
        for e in has_trait:
            cid, tid = e.get("from_id"), e.get("to_id")
            trait = self.vertices.get(tid, {})
            key, val = trait.get("key"), trait.get("value")
            immutable = trait.get("is_immutable") in (True, "True", "true", 1)
            if cid and key:
                char_trait_index.setdefault((cid, key), []).append(
                    {"value": val, "is_immutable": immutable}
                )

        for (cid, trait_key), entries in char_trait_index.items():
            values = [e["value"] for e in entries]
            if len(set(str(v) for v in values)) > 1:
                is_imm = any(e["is_immutable"] for e in entries)
                char_name = (self.get_character(cid) or {}).get("name", cid)
                violations.append(_make_violation(
                    vtype=ContradictionType.TRAIT,
                    severity=Severity.CRITICAL if is_imm else Severity.MAJOR,
                    description=f"캐릭터 '{char_name}'의 특성 '{trait_key}': {values}",
                    confidence=0.95 if is_imm else 0.6,
                    character_id=cid, character_name=char_name,
                    evidence=[{"trait_key": trait_key, "values": values}],
                    needs_user_input=not is_imm,
                    confirmation_type=ConfirmationType.INTENTIONAL_CHANGE if not is_imm else None,
                    suggestion=f"'{trait_key}' 특성 값을 통일하거나 변화 이유를 명시하세요.",
                ))
        return violations

    def find_emotion_violations(self) -> List[Dict[str, Any]]:
        """5. 감정 일관성"""
        violations = []
        feels = self._edges_by_label("FEELS")
        pair_emotions: Dict[Tuple[str, str], List[Dict]] = {}
        for e in feels:
            fid, tid = e.get("from_id"), e.get("to_id")
            if fid and tid:
                pair_emotions.setdefault((fid, tid), []).append(e)

        OPPOSITES = {
            frozenset(["love", "hate"]),
            frozenset(["trust", "distrust"]),
            frozenset(["admiration", "contempt"]),
            frozenset(["gratitude", "resentment"]),
        }
        for (fid, tid), history in pair_emotions.items():
            sorted_h = sorted(history, key=lambda x: float(x.get("discourse_order") or 0))
            for i in range(1, len(sorted_h)):
                prev, curr = sorted_h[i - 1], sorted_h[i]
                pair = frozenset([str(prev.get("emotion")), str(curr.get("emotion"))])
                if pair in OPPOSITES and not curr.get("trigger_event_id"):
                    char_name = (self.get_character(fid) or {}).get("name", fid)
                    violations.append(_make_violation(
                        vtype=ContradictionType.EMOTION,
                        severity=Severity.MAJOR,
                        description=(
                            f"캐릭터 '{char_name}'의 감정이 트리거 없이 "
                            f"{prev.get('emotion')} → {curr.get('emotion')} 급변"
                        ),
                        confidence=0.6,
                        character_id=fid, character_name=char_name,
                        evidence=[{"prev": prev.get("emotion"), "curr": curr.get("emotion")}],
                        needs_user_input=True,
                        confirmation_type=ConfirmationType.EMOTION_SHIFT,
                        suggestion="감정 변화를 유발한 이벤트를 명시하거나 감정 추이를 자연스럽게 조정하세요.",
                    ))
        return violations

    def find_item_violations(self) -> List[Dict[str, Any]]:
        """6. 소유물 추적"""
        violations = []
        possesses = self._edges_by_label("POSSESSES")
        loses = self._edges_by_label("LOSES")

        item_history: Dict[str, List[Dict]] = {}
        for e in possesses:
            iid = e.get("to_id")
            if iid:
                item_history.setdefault(iid, []).append({
                    "type": "possesses", "char_id": e.get("from_id"),
                    "story_order": e.get("story_order"),
                })
        for e in loses:
            iid = e.get("to_id")
            if iid:
                item_history.setdefault(iid, []).append({
                    "type": "loses", "char_id": e.get("from_id"),
                    "story_order": e.get("story_order"),
                })

        for item_id, history in item_history.items():
            item_name = (self.get_item(item_id) or {}).get("name", item_id)
            sorted_h = [h for h in history if h.get("story_order") is not None]
            sorted_h.sort(key=lambda x: float(x["story_order"]))

            # 동시 이중 소유
            time_owners: Dict[float, List[str]] = defaultdict(list)
            for h in sorted_h:
                if h["type"] == "possesses":
                    time_owners[float(h["story_order"])].append(h["char_id"])
            for so, owners in time_owners.items():
                if len(set(owners)) > 1:
                    violations.append(_make_violation(
                        vtype=ContradictionType.ITEM,
                        severity=Severity.CRITICAL,
                        description=f"아이템 '{item_name}'이 story_order={so}에 {len(owners)}명에게 동시 소유",
                        confidence=0.95,
                        evidence=[{"item_id": item_id, "story_order": so, "owners": owners}],
                        suggestion="동시 소유 중 하나의 story_order를 조정하거나 소유권 이전을 추가하세요.",
                    ))

            # 분실 후 재소유
            last_loses: Dict[str, float] = {}
            for h in sorted_h:
                if h["type"] == "loses":
                    last_loses[h["char_id"]] = float(h["story_order"])
                elif h["type"] == "possesses":
                    cid, so = h["char_id"], float(h["story_order"])
                    lost_at = last_loses.get(cid)
                    if lost_at is not None and so > lost_at:
                        char_name = (self.get_character(cid) or {}).get("name", cid)
                        violations.append(_make_violation(
                            vtype=ContradictionType.ITEM,
                            severity=Severity.MAJOR,
                            description=(
                                f"캐릭터 '{char_name}'이(가) '{item_name}' 분실(story_order={lost_at}) "
                                f"후 재소유(story_order={so})"
                            ),
                            confidence=0.65,
                            character_id=cid, character_name=char_name,
                            evidence=[{"lost_at": lost_at, "repossessed_at": so}],
                            needs_user_input=True,
                            confirmation_type=ConfirmationType.ITEM_DISCREPANCY,
                        ))
        return violations

    def find_deception_violations(self) -> List[Dict[str, Any]]:
        """7. 거짓말·기만"""
        violations = []
        facts = {v["id"]: v for v in self._vertices_by_label("fact")}
        learns = self._edges_by_label("LEARNS")
        mentions = self._edges_by_label("MENTIONS")

        false_fact_ids = {
            fid for fid, fv in facts.items()
            if fv.get("is_true") in (False, "False", "false", 0)
        }

        believed_false: Dict[Tuple[str, str], float] = {}
        for e in learns:
            fid, cid = e.get("to_id"), e.get("from_id")
            believed = e.get("believed_true", True)
            so = e.get("story_order")
            if fid in false_fact_ids and believed in (True, "True", "true", 1):
                if cid and so is not None:
                    believed_false[(cid, fid)] = float(so)

        truth_learn: Dict[Tuple[str, str], float] = {}
        for e in learns:
            fid, cid = e.get("to_id"), e.get("from_id")
            believed = e.get("believed_true", True)
            so = e.get("story_order")
            if fid not in false_fact_ids and believed in (True, "True", "true", 1):
                if cid and so is not None:
                    key = (cid, fid)
                    if key not in truth_learn or float(so) < truth_learn[key]:
                        truth_learn[key] = float(so)

        for e in mentions:
            cid, fid, so = e.get("from_id"), e.get("to_id"), e.get("story_order")
            if not (cid and fid and so is not None and fid in false_fact_ids):
                continue
            so = float(so)
            truth_so = truth_learn.get((cid, fid))
            if truth_so is not None and so > truth_so:
                char_name = (self.get_character(cid) or {}).get("name", cid)
                violations.append(_make_violation(
                    vtype=ContradictionType.DECEPTION,
                    severity=Severity.CRITICAL,
                    description=(
                        f"캐릭터 '{char_name}'이(가) 진실 인지(story_order={truth_so}) 후에도 "
                        f"거짓 사실을 언급(story_order={so})"
                    ),
                    confidence=0.9,
                    character_id=cid, character_name=char_name,
                    dialogue=e.get("dialogue_text"),
                    evidence=[{"truth_learned_at": truth_so, "false_mention_at": so}],
                    suggestion="진실 인지 후 거짓 정보 전달의 의도를 명시하거나 제거하세요.",
                ))

        for (cid, fid), so in believed_false.items():
            char_name = (self.get_character(cid) or {}).get("name", cid)
            violations.append(_make_violation(
                vtype=ContradictionType.DECEPTION,
                severity=Severity.MINOR,
                description=f"캐릭터 '{char_name}'이(가) 거짓 사실을 진실로 학습(story_order={so})",
                confidence=0.55,
                character_id=cid, character_name=char_name,
                evidence=[{"fact_id": fid, "believed_true_at": so}],
                needs_user_input=True,
                confirmation_type=ConfirmationType.UNRELIABLE_NARRATOR,
            ))
        return violations

    def find_all_violations(self) -> Dict[str, List[Dict[str, Any]]]:
        """7가지 쿼리 통합 + Hard / Soft 분류"""
        all_v = (
            self.find_knowledge_violations()
            + self.find_timeline_violations()
            + self.find_relationship_violations()
            + self.find_trait_violations()
            + self.find_emotion_violations()
            + self.find_item_violations()
            + self.find_deception_violations()
        )
        hard = [v for v in all_v if v.get("is_hard")]
        soft = [v for v in all_v if not v.get("is_hard")]
        logger.info("find_all_violations complete", hard=len(hard), soft=len(soft), total=len(all_v))
        return {"hard": hard, "soft": soft, "all": all_v}

    def snapshot_graph(self, relevant_ids: Optional[List[str]] = None) -> "InMemoryGraphService":
        """자신의 딥카피 반환 (원본 불변 보장)"""
        snap = InMemoryGraphService()
        if relevant_ids:
            id_set = set(relevant_ids)
            snap.vertices = {k: copy.deepcopy(v) for k, v in self.vertices.items() if k in id_set}
            snap.edges = [
                copy.deepcopy(e) for e in self.edges
                if e.get("from_id") in id_set or e.get("to_id") in id_set
            ]
        else:
            snap.vertices = copy.deepcopy(self.vertices)
            snap.edges = copy.deepcopy(self.edges)
        snap._discourse_counter = self._discourse_counter
        return snap

    def get_character_knowledge_at(self, character_id: str, story_order: float) -> List[Dict]:
        return [
            e for e in self._edges_by_label("LEARNS")
            if e.get("from_id") == character_id
            and e.get("story_order") is not None
            and float(e["story_order"]) <= story_order
        ]

    def get_stats(self) -> KBStats:
        return KBStats(
            characters=len(self._vertices_by_label("character")),
            facts=len(self._vertices_by_label("fact")),
            relationships=len(self._edges_by_label("RELATED_TO")),
            events=len(self._vertices_by_label("event")),
            traits=len(self._vertices_by_label("trait")),
            locations=len(self._vertices_by_label("location")),
            items=len(self._vertices_by_label("item")),
            organizations=len(self._vertices_by_label("organization")),
            sources=len(self._vertices_by_label("source")),
            confirmations=len(self._vertices_by_label("confirmation")),
        )

    def remove_source(self, source_id: str) -> Dict[str, int]:
        orig_v, orig_e = len(self.vertices), len(self.edges)
        self.vertices = {k: v for k, v in self.vertices.items() if v.get("source_id") != source_id}
        remaining = set(self.vertices.keys())
        self.edges = [
            e for e in self.edges
            if e.get("source_id") != source_id
            and e.get("from_id") in remaining
            and e.get("to_id") in remaining
        ]
        removed = {"vertices": orig_v - len(self.vertices), "edges": orig_e - len(self.edges)}
        logger.info("remove_source complete", source_id=source_id, **removed)
        return removed
