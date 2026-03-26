"""중복 제거 로직 단위 테스트 (Azure 호출 없음).

이전 case2 E2E 실행에서 확인된 중복 패턴을 재현하여
dedup 로직이 올바르게 동작하는지 검증합니다.

실행: python scripts/test_dedup_logic.py
"""
import re
import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.graph import _make_violation
from app.models.enums import ContradictionType, Severity, ConfirmationType


def _extract_keywords(text: str) -> set:
    """한글 텍스트에서 조사/어미를 제거한 핵심 키워드 추출."""
    nums = set(re.findall(r'\d+[분시간일월년]', text))
    words = re.findall(r'[가-힣]+', text)
    cleaned = set()
    for w in words:
        w = re.sub(
            r'(에서|까지는|까지|으로는|에서의|이라|으로|에게|한테'
            r'|하며|하는데|했다고|되어|있어|가능|통해서만|통해|걸려야'
            r'|만에|하는|인데|있는|했다|된다|한다|이다|하여|대로'
            r'|이지만|라는|라고|에는|으며|이며|에도|지만|이나)$', '', w)
        w = re.sub(r'(을|를|이|가|은|는|의|에|로|과|와|도|서|만|씩|들|째)$', '', w)
        if len(w) >= 2:
            cleaned.add(w)
    return cleaned | nums


# ── 헬퍼 ────────────────────────────────────────────────────

def _common_substring_len(a: str, b: str) -> int:
    if not a or not b:
        return 0
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    for length in range(len(short), 9, -1):
        for start in range(len(short) - length + 1):
            if short[start:start+length] in long_:
                return length
    return 0


def cross_dedup_world_violations(graph_violations, world_violations):
    """테스트 스크립트의 cross-dedup 로직 (case2_e2e_test.py와 동일)."""
    hard = [v for v in graph_violations if v.get("is_hard")]
    soft = [v for v in graph_violations if not v.get("is_hard")]

    # fact key + description 키워드 수집
    existing_fact_keys = set()
    existing_desc_kw = []
    for v in hard + soft:
        for ev in v.get("evidence") or []:
            if isinstance(ev, dict):
                ft = str(ev.get("fact_content") or ev.get("fact") or ev.get("rule") or "")
                if ft and len(ft) > 10:
                    existing_fact_keys.add(ft[:60])
        existing_desc_kw.append(_extract_keywords(v.get("description", "")))

    added = []
    skipped = []
    for v in world_violations:
        is_dup = False
        dup_idx = -1  # 중복 대상의 인덱스 (hard 우선을 위해)

        # 1) evidence fact/rule 부분문자열 매칭
        for ev in v.get("evidence") or []:
            if isinstance(ev, dict):
                rule = str(ev.get("rule") or "")
                if rule and len(rule) > 10:
                    rule_short = rule[:60]
                    for existing in existing_fact_keys:
                        shorter = min(rule_short, existing, key=len)
                        longer = max(rule_short, existing, key=len)
                        if shorter in longer or _common_substring_len(shorter, longer) >= 20:
                            is_dup = True
                            break
                if is_dup:
                    break

        # 2) description 키워드 Jaccard 보조
        if not is_dup:
            v_kw = _extract_keywords(v.get("description", ""))
            if v_kw and len(v_kw) >= 3:
                all_existing = hard + soft
                for idx, prev_v in enumerate(all_existing):
                    prev_kw = _extract_keywords(prev_v.get("description", ""))
                    if not prev_kw:
                        continue
                    union = v_kw | prev_kw
                    inter = v_kw & prev_kw
                    if not union:
                        continue
                    jac = len(inter) / len(union)
                    if jac > 0.5 or (jac > 0.3 and len(inter) >= 3):
                        is_dup = True
                        dup_idx = idx
                        break

        if is_dup:
            # Hard 우선: LLM hard가 기존 soft와 중복이면 → soft 제거, hard 유지
            if v.get("is_hard") and dup_idx >= 0:
                all_existing = hard + soft
                if dup_idx < len(all_existing) and not all_existing[dup_idx].get("is_hard"):
                    dup_v = all_existing[dup_idx]
                    if dup_v in soft:
                        soft.remove(dup_v)
                    # LLM hard를 추가
                    hard.append(v)
                    added.append(v)
                    existing_desc_kw.append(_extract_keywords(v.get("description", "")))
                    continue
            skipped.append(v)
            continue
        for ev in v.get("evidence") or []:
            if isinstance(ev, dict):
                rule = str(ev.get("rule") or "")
                if rule and len(rule) > 10:
                    existing_fact_keys.add(rule[:60])
        existing_desc_kw.append(_extract_keywords(v.get("description", "")))
        added.append(v)
        if v.get("is_hard"):
            hard.append(v)
        else:
            soft.append(v)

    # soft에서 hard와 중복 제거 (키워드 기반)
    hard_kw = [_extract_keywords(v.get("description", "")) for v in hard]
    deduped_soft = []
    for v in soft:
        s_kw = _extract_keywords(v.get("description", ""))
        is_dup = False
        if s_kw and len(s_kw) >= 2:
            for hk in hard_kw:
                union = s_kw | hk
                inter = s_kw & hk
                if union and len(inter) / len(union) > 0.35:
                    is_dup = True
                    break
        if not is_dup:
            deduped_soft.append(v)
    soft = deduped_soft

    return hard, soft, added, skipped


def llm_internal_dedup(violations):
    """LLM 내부 중복 제거 (detection.py _check_world_rules_with_llm 결과 병합)."""
    deduped = []
    seen_rule_event = set()
    seen_desc_parts = []

    for v in violations:
        ev_list = v.get("evidence") or []
        rule_t = ""
        event_t = ""
        for ev_item in ev_list:
            if isinstance(ev_item, dict):
                rule_t = str(ev_item.get("rule", ""))[:50]
                event_t = str(ev_item.get("event", ""))[:50]

        if rule_t and event_t:
            re_key = (rule_t, event_t)
            if re_key in seen_rule_event:
                continue
            seen_rule_event.add(re_key)

        desc = v.get("description", "")
        parts = set(re.findall(r'[가-힣]{2,}', desc))
        is_dup = False
        for prev in seen_desc_parts:
            union = parts | prev
            inter = parts & prev
            if union and len(inter) / len(union) > 0.5:
                is_dup = True
                break
        if is_dup:
            continue
        seen_desc_parts.append(parts)
        deduped.append(v)

    return deduped


# ── 테스트 데이터 (이전 case2 실행 결과에서 수집) ──────────────

def make_graph_violation(desc, fact_content, is_hard=True, vtype=ContradictionType.TIMELINE, conf=0.95):
    return _make_violation(
        vtype=vtype,
        severity=Severity.CRITICAL if is_hard else Severity.MAJOR,
        description=desc,
        confidence=conf,
        evidence=[{"fact": fact_content, "story_order": 1.0}],
        needs_user_input=not is_hard,
        confirmation_type=None if is_hard else ConfirmationType.TIMELINE_AMBIGUITY,
    )

def make_llm_violation(desc, rule_content, event_content, is_hard=True, conf=0.95):
    return _make_violation(
        vtype=ContradictionType.TIMELINE,
        severity=Severity.CRITICAL if is_hard else Severity.MAJOR,
        description=desc,
        confidence=conf,
        evidence=[{"rule": rule_content, "event": event_content, "story_order": 1.0}],
        needs_user_input=not is_hard,
        confirmation_type=None if is_hard else ConfirmationType.TIMELINE_AMBIGUITY,
    )

def make_trait_violation(desc, char_name, is_hard=False, conf=0.70):
    return _make_violation(
        vtype=ContradictionType.TRAIT,
        severity=Severity.MAJOR,
        description=desc,
        confidence=conf,
        character_name=char_name,
        evidence=[{"trait": desc}],
        needs_user_input=True,
        confirmation_type=ConfirmationType.INTENTIONAL_CHANGE,
    )


# ── 테스트 케이스 ─────────────────────────────────────────

def test_1_travel_time_dup():
    """test_1: 구조적 '12분→4분 이동' + LLM '12분→4분 이동' → 중복 제거"""
    FACT = "중앙 통제실에서 엔진실까지는 감압 통로를 통해 최소 12분이 소요된다"

    graph_v = [
        make_graph_violation(
            "세계 규칙 위반 — 최소 12분 소요 구간을 4분 만에 이동(story_order=0.9): 오후 11시 14분 태하가 통제실을 떠난 지 4분 만에 엔진실에 도착",
            fact_content=FACT,
        ),
        make_graph_violation(
            "세계 규칙 위반 — 11시 이후 봉쇄 구역에 11시 이동/진입(story_order=0.7)",
            fact_content="오후 11시 이후 봉쇄 구역 출입이 금지된다",
        ),
        make_graph_violation(
            "캐릭터 '오선우'이(가) 사망(story_order=1.2) 후 이벤트에 등장(story_order=1.3)",
            fact_content="사망 후 등장",
        ),
    ]

    llm_v = [
        make_llm_violation(
            "중앙 통제실에서 엔진실까지는 감압 통로를 통해 최소 12분이 걸려야 하는데, 태하는 통제실을 떠난 지 4분 만에 엔진실에 도착했다.",
            rule_content=FACT,
            event_content="태하가 통제실을 떠난 지 4분 만에 엔진실에 도착",
            conf=0.98,
        ),
    ]

    hard, soft, added, skipped = cross_dedup_world_violations(graph_v, llm_v)
    total = len(hard) + len(soft)
    assert len(skipped) == 1, f"LLM 이동시간 중복이 제거되어야 함. skipped={len(skipped)}"
    assert total == 3, f"총 3건이어야 함 (사망+봉쇄+이동시간). got {total}"
    return True, f"PASS: 3건 유지, 1건 중복 제거"


def test_2_travel_time_dup():
    """test_2: 구조적 '10분→2분 이동' + LLM '10분→2분 이동' → 중복 제거"""
    FACT = "A구역에서 B구역까지 케이블 포드 이동은 편도 10분이 소요된다"

    graph_v = [
        make_graph_violation(
            "세계 규칙 위반 — 최소 10분 소요 구간을 2분 만에 이동: 나린이 2분 만에 B구역 게이트 도착",
            fact_content=FACT,
        ),
        make_trait_violation(
            "캐릭터 '나린'의 특성 '고소공포증이 심해 케이블 포드를 절대 타지 않는다' 위반",
            char_name="나린", is_hard=True, conf=0.85,
        ),
    ]

    llm_v = [
        make_llm_violation(
            "A구역에서 B구역으로 이동하는 케이블 포드는 편도 10분이 걸린다고 규정되어 있는데, 나린은 7시 30분에 탑승한 뒤 2분 만에 B구역 게이트에 도착했다.",
            rule_content=FACT,
            event_content="나린이 2분 만에 B구역 게이트에 도착",
            conf=0.96,
        ),
        make_llm_violation(
            "자정부터 오전 4시까지는 도시 외부망 접속이 차단된다고 되어 있는데, 오전 0시 30분에 준이 도시 단말기로 외부 뉴스망에 실시간 접속한다.",
            rule_content="자정~오전 4시 도시 외부망 접속 차단",
            event_content="오전 0시 30분 준이 외부 뉴스망 접속",
            conf=0.95,
        ),
    ]

    hard, soft, added, skipped = cross_dedup_world_violations(graph_v, llm_v)
    total = len(hard) + len(soft)
    assert len(skipped) == 1, f"이동시간 중복 1건 제거. skipped={len(skipped)}"
    assert len(added) == 1, f"외부망 접속은 새 탐지로 유지. added={len(added)}"
    return True, f"PASS: {total}건 유지, 1건 중복 제거"


def test_4_lockout_dup():
    """test_4: 구조적 '9시 이후 성문 봉쇄' + LLM '성문 봉쇄' → 중복 제거"""
    FACT = "해가 진 뒤(밤 9시) 성문은 봉쇄된다"

    graph_v = [
        make_graph_violation(
            "세계 규칙 위반 — 9시 이후 봉쇄 구역에 9시 이동/진입: 밤 9시에 성문이 봉쇄된 후에도 일행이 서문으로 외부로 빠져나간다",
            fact_content=FACT,
        ),
        make_graph_violation(
            "세계 규칙 위반 — 최소 3시간 소요 구간을 20분 만에 이동",
            fact_content="수도 오아시스에서 태양문 유적까지 낙타로 최소 3시간이 소요된다",
        ),
    ]

    llm_v = [
        make_llm_violation(
            "성문은 밤 9시 이후 봉쇄되는데, 밤 9시에 성문이 봉쇄된 뒤에도 일행이 서문을 통해 외부로 빠져나간다.",
            rule_content=FACT,
            event_content="일행이 서문을 통해 외부로 빠져나감",
            conf=0.95,
        ),
        make_llm_violation(
            "정오(12~14시)에는 야외에서 금속 장비 사용이 금지되어 있는데, 12시 30분에 레아가 야외에서 강철 창을 휘두르며 훈련하고 있다.",
            rule_content="정오 12시~14시 야외 금속 장비 사용 금지",
            event_content="12시 30분 레아가 강철 창 훈련",
            conf=0.99,
        ),
    ]

    hard, soft, added, skipped = cross_dedup_world_violations(graph_v, llm_v)
    total = len(hard) + len(soft)
    assert len(skipped) == 1, f"성문 봉쇄 중복 1건 제거. skipped={len(skipped)}"
    assert len(added) == 1, f"금속 장비 금지는 새 탐지로 유지. added={len(added)}"
    return True, f"PASS: {total}건 유지, 1건 중복 제거"


def test_5_caffeine_dup():
    """test_5: LLM 내부 중복 — '카페인 과민증' 2건 → 1건"""
    llm_v = [
        make_llm_violation(
            "서준은 카페인 과민증이 있다는 설정인데, 1세트 진행 중 더블 에스프레소를 마시는 행동은 해당 신체적 제약 설정과 충돌한다.",
            rule_content="서준은 카페인 과민증이 있어 커피와 에너지 음료를 전혀 마시지 않는다",
            event_content="서준이 더블 에스프레소를 마심",
            conf=0.93,
        ),
        make_llm_violation(
            "서준은 커피와 에너지 음료를 전혀 마시지 않는다는 설정이 있는데, 경기 중 더블 에스프레소를 마시는 장면은 이 규칙을 직접적으로 위반한다.",
            rule_content="서준은 카페인 과민증이 있어 커피와 에너지 음료를 전혀 마시지 않는다",
            event_content="서준이 더블 에스프레소를 마심",
            conf=0.98,
        ),
    ]

    deduped = llm_internal_dedup(llm_v)
    assert len(deduped) == 1, f"동일 rule+event → 1건. got {len(deduped)}"
    return True, f"PASS: 2건 → 1건 (LLM 내부 exact dedup)"


def test_3_court_seal_dup():
    """test_3: LLM이 법정 봉인 위반을 다른 표현으로 2건 출력 → 1건"""
    llm_v = [
        make_llm_violation(
            "심리가 시작되면 법정 출입문은 종결 전까지 봉인되어 출입이 불가능하다. 그런데 정하늘 검사가 금고 USB를 들고 같은 법정으로 '복귀'했다.",
            rule_content="심리 개시와 동시에 법정 출입문이 봉인되며 종결 전까지 출입 불가",
            event_content="정하늘 검사가 법정으로 복귀",
            conf=0.93,
        ),
        make_llm_violation(
            "심리 시작 후 법정 출입문이 봉인되므로 외부로 나갈 수 없다. 그러나 정하늘이 금고에 다녀왔다고 말하는 것은 법정을 나갔다가 돌아왔다는 의미로 규칙에 위배된다.",
            rule_content="심리 개시와 동시에 법정 출입문이 봉인되며 종결 전까지 출입 불가",
            event_content="정하늘 검사가 법정으로 복귀",
            conf=0.92,
        ),
    ]

    deduped = llm_internal_dedup(llm_v)
    assert len(deduped) == 1, f"동일 rule+event → 1건. got {len(deduped)}"
    return True, f"PASS: 2건 → 1건 (LLM 내부 exact dedup)"


def test_7_death_and_travel_dup():
    """test_7: 구조적 사망후등장 + LLM 사망후등장, 구조적 이동시간 + LLM 이동시간"""
    graph_v = [
        make_graph_violation(
            "캐릭터 '제온'이(가) 사망(story_order=0.0) 후 이벤트에 등장(story_order=1.1): 사망한 제온이 격납고 관제실에서 탈출 계획을 지시한다",
            fact_content="제온 사망",
        ),
        make_graph_violation(
            "세계 규칙 위반 — 최소 25분 소요 구간을 8분 만에 이동: 오전 1시 20분에 하로가 8분 만에 독방에서 격납고에 도착한다",
            fact_content="A동 독방에서 격납고까지 보안 절차 포함 최소 25분이 소요된다",
        ),
    ]

    llm_v = [
        make_llm_violation(
            "제온은 어제 공개 처형으로 사망이 확정되었는데, 격납고 관제실에서 탈출 계획을 지시하는 장면이 등장해 사망 설정과 충돌한다.",
            rule_content="제온은 어제 공개 처형으로 사망이 확정",
            event_content="사망한 제온이 격납고에서 탈출 지시",
            conf=0.98,
        ),
        make_llm_violation(
            "A동 독방에서 격납고까지 최소 25분이 걸려야 하는데, 하로가 8분 만에 도착했다고 기록되어 이동 시간 규칙을 위반한다.",
            rule_content="A동 독방에서 격납고까지 보안 절차 포함 최소 25분이 소요된다",
            event_content="하로가 8분 만에 도착",
            conf=0.96,
        ),
        make_llm_violation(
            "오전 1시~5시는 전 구역 외부 통신이 차단되어야 하는데, 오전 1시 10분에 하로가 외부 스트리밍 채널로 라이브 통화를 시작했다.",
            rule_content="오전 1시~5시 전 구역 외부 통신 차단",
            event_content="하로가 외부 스트리밍 라이브 통화",
            conf=0.97,
        ),
        make_llm_violation(
            "독방 문은 교도소장 손바닥 인증과 수감자 칩 동시 인식으로만 열리는데, 기술요원이 코드 입력만으로 문을 열었다.",
            rule_content="독방 문은 교도소장 손바닥 인증 + 수감자 칩 동시 인식으로만 개방",
            event_content="기술요원이 코드 입력만으로 문을 열음",
            conf=0.95,
        ),
    ]

    hard, soft, added, skipped = cross_dedup_world_violations(graph_v, llm_v)
    total = len(hard) + len(soft)
    assert len(skipped) == 2, f"사망+이동시간 2건 중복 제거. skipped={len(skipped)}"
    assert len(added) == 2, f"통신차단+독방문 2건 새 탐지. added={len(added)}"
    assert total == 4, f"총 4건 (구조2 + LLM 신규2). got {total}"
    return True, f"PASS: 6건 입력 → 4건 (2건 중복 제거)"


def test_8_trait_llm_dup():
    """test_8: LLM Hard '주사 공포증' + trait Soft '주사 공포증' → Hard만 유지"""
    graph_v = [
        make_graph_violation(
            "세계 규칙 위반 — 최소 12분 소요 구간을 3분 만에 이동: 하나가 약제실에서 3분 만에 중환자실에 도착",
            fact_content="약제실에서 중환자실까지 보안 구역 통과 포함 최소 12분이 소요된다",
        ),
        make_trait_violation(
            "캐릭터 '하나'의 특성 '주사 공포증으로 직접 주사를 놓지 않는다' 위반 행동 발생: 처치실에서 하나가 침착하게 정맥주사를 놓는다",
            char_name="하나",
        ),
        make_trait_violation(
            "캐릭터 '정민'의 특성 '상태: 뇌사 판정으로 의식 불가' 위반 행동 발생: 뇌사 판정된 정민이 눈을 뜨고 또렷하게 대화한다",
            char_name="정민",
        ),
    ]

    llm_v = [
        make_llm_violation(
            "하나는 주사 공포증이 있어 직접 주사를 놓지 않는다는 설정이 있는데, 이벤트에서 침착하게 정맥주사를 직접 놓는다.",
            rule_content="하나는 주사 공포증이 있어 직접 주사를 놓지 않는다",
            event_content="하나가 침착하게 정맥주사를 놓음",
            conf=0.96,
        ),
        make_llm_violation(
            "정민은 뇌사 판정으로 의식이 없다는 설정인데, 이벤트에서 눈을 뜨고 또렷하게 대화한다.",
            rule_content="정민은 뇌사 판정으로 의식 불가",
            event_content="정민이 눈을 뜨고 대화",
            conf=0.99,
        ),
        make_llm_violation(
            "독성 구역에 진입하려면 산소 탱크 착용이 필수라는 규칙이 있는데, 하나가 산소 탱크 없이 독성 구역으로 들어간다.",
            rule_content="독성 구역 진입 시 산소 탱크 착용 필수",
            event_content="하나가 산소 탱크 없이 독성 구역 진입",
            conf=1.0,
        ),
    ]

    hard, soft, added, skipped = cross_dedup_world_violations(graph_v, llm_v)
    total = len(hard) + len(soft)
    # LLM의 주사공포증/뇌사판정은 새 탐지로 추가 (evidence fact 매칭 안 됨)
    # 하지만 최종 soft→hard dedup에서 trait soft가 LLM hard와 겹치면 제거
    print(f"    hard={len(hard)}, soft={len(soft)}, added={len(added)}, skipped={len(skipped)}")
    for v in hard:
        print(f"      [HARD] {v.get('description', '')[:80]}")
    for v in soft:
        print(f"      [SOFT] {v.get('description', '')[:80]}")

    # trait soft 2건이 LLM hard와 중복 → soft에서 제거되어야 함
    # 기대: hard=4 (구조1 + LLM3), soft=0 (trait 2건 제거)
    # 또는: hard=4, soft=0~1 (산소탱크는 새 탐지)
    assert len(soft) <= 1, f"trait soft가 LLM hard와 중복이면 제거. soft={len(soft)}"
    return True, f"PASS: hard={len(hard)}, soft={len(soft)} (trait-LLM 중복 제거)"


# ── 메인 ─────────────────────────────────────────────────

def main():
    tests = [
        ("test_1: 구조적↔LLM 이동시간 중복", test_1_travel_time_dup),
        ("test_2: 구조적↔LLM 이동시간 중복 + 새 탐지 유지", test_2_travel_time_dup),
        ("test_3: LLM 내부 법정 봉인 2건→1건", test_3_court_seal_dup),
        ("test_4: 구조적↔LLM 성문 봉쇄 중복", test_4_lockout_dup),
        ("test_5: LLM 내부 카페인 과민증 2건→1건", test_5_caffeine_dup),
        ("test_7: 사망+이동시간 각각 구조적↔LLM 중복", test_7_death_and_travel_dup),
        ("test_8: LLM Hard↔trait Soft 중복", test_8_trait_llm_dup),
    ]

    print("=" * 70)
    print("  중복 제거 로직 단위 테스트 (Azure 호출 없음)")
    print("=" * 70)

    passed = 0
    failed = 0
    for name, fn in tests:
        print(f"\n  {name}")
        try:
            ok, msg = fn()
            if ok:
                print(f"    → {msg}")
                passed += 1
            else:
                print(f"    → FAIL: {msg}")
                failed += 1
        except AssertionError as e:
            print(f"    → FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"    → ERROR: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'=' * 70}")
    print(f"  결과: {passed}/{passed+failed} 통과")
    print(f"{'=' * 70}")
    return failed == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
