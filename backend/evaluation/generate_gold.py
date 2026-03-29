"""expectation 텍스트 파일 → Gold Standard 자동 변환 스크립트.

실행: cd backend && python -m evaluation.generate_gold
출력: evaluation/gold_standard_cases.py
"""
import os
import re
import json
import sys
from typing import List, Tuple

# ── 카테고리 자동 분류 규칙 ──────────────────────────────────────

CATEGORY_RULES = [
    # (패턴 키워드 리스트, 카테고리)  — 먼저 매칭된 것이 우선
    # 1. 사망 후 재등장
    (["사망", "시체", "재등장", "사망 후", "죽은", "사망 판정", "처형",
      "사망자", "부활", "죽었", "사망했", "눈을 뜬", "의식을 잃"],
     "DEATH_REAPPEAR"),
    # 2. 이동/타임라인 (시간, 거리, 위치 이동)
    (["이동 시간", "분 소요", "분 만에", "분 규칙", "분 이동", "도보",
      "소요 시간", "분이 걸", "분이면", "분 거리", "\\d+분",
      "위치가 바뀌", "장소가 바뀌", "장소가 다", "위치가 다",
      "에 있는데.*에 있", "도쿄.*방콕", "방콕.*도쿄",
      "에펠탑", "지리적", "출발.*도착", "도착.*출발"],
     "TIMELINE_MOVE"),
    # 3. 정보 비대칭
    (["정보 비대칭", "알고 있", "전에 알", "먼저 알", "인지 전",
      "정보를 알", "이미 알", "알 수 없", "몰랐", "모르는데",
      "확인 전에", "발견 전에", "전에.*사실을", "전부터.*알",
      "어떻게 알", "듣기 전"],
     "INFO_ASYMMETRY"),
    # 4. 보안/소유 아이템
    (["열쇠", "카드", "마스터키", "토큰", "유일", "단 하나", "복제",
      "양도 불가", "소유.*위반", "보안 카드", "인증.*키",
      "하나뿐", "하나인데.*둘", "동시에 가지"],
     "SECURITY_ITEM"),
    # 5. 물리/규칙 위반 (세계 규칙, 환경, 날씨, 계절, 통제)
    (["봉쇄", "금지", "잠금", "잠긴", "통제", "블랙아웃", "통신 차단",
      "봉인", "규칙 위반", "법칙", "물리적", "우주복", "장비 없이",
      "마법 봉인", "불가능", "조약", "전면 금지",
      # 날씨/환경 모순
      "날씨", "비가.*맑", "맑.*비가", "눈이.*비", "비.*눈이",
      "하늘.*비", "노을.*비", "폭우.*맑", "맑.*폭우",
      "보름달.*그믐", "그믐.*보름달", "달빛.*그믐", "달이 없.*달빛",
      "별.*보이지 않.*별빛", "별빛.*별.*보이지",
      # 계절/온도 모순
      "벚꽃.*12월", "12월.*벚꽃", "겨울.*벚꽃", "벚꽃.*겨울",
      "패딩.*반팔", "반팔.*패딩",
      # 환경 불일치
      "산.*바다", "바다.*산", "민물.*바다", "바다.*민물",
      "해수.*민물", "민물.*해수", "산장.*파도", "파도.*산장",
      # 기술/장비 제약
      "통신.*차단.*통화", "통화.*차단", "네트워크.*없.*접속",
      "신호.*없.*통화", "장비.*없이.*외부",
      # 능력/자격 제약
      "마법.*사용할 수 없", "마법이 봉인.*마법을 사용",
      "불가.*했지만.*한다", "금지.*했지만"],
     "PHYSICS_RULE"),
    # 6. 관계/문서 모순
    (["관계.*모순", "어머니.*남매", "남매.*어머니", "형제.*부모",
      "부모.*형제", "배우자.*형제", "동료.*적", "적.*동료",
      "가족 관계", "관계가 바뀌", "관계.*동시"],
     "OTHER"),
    # 7. 설정/성격 모순 (가장 광범위 — 마지막에 배치)
    (["성격", "습관", "혐오", "극혐", "절대 안", "체질", "설정",
      "특성", "입에 대지", "손잡이", "외모", "머리", "품종", "견종",
      "고양이", "혈액형", "채식", "의족", "시력", "알레르기",
      "공포증", "마시", "먹", "의족 위치",
      # 외모/물리 속성 변경
      "머리.*색", "색.*바뀌", "바뀐다", "바뀜", "달라",
      "빨간.*검은", "검은.*빨간", "파란.*빨간", "빨간.*파란",
      "금발.*흰", "흰.*검은", "곱슬.*스트레이트", "스트레이트.*곱슬",
      # 수치 모순 (나이, 횟수, 인원)
      "나이.*맞지 않", "살.*살", "살이.*다르",
      "번째.*번째", "처음.*번째", "ù.*번째",
      "명.*명", "인원.*맞지", "인원.*다르",
      # 점수/결과 모순
      "이겼.*졌", "졌.*이겼", "승리.*패배", "패배.*승리",
      "MVP.*득점", "레이업.*삼점", "삼점.*레이업",
      # 입양/구매 경로
      "입양.*펫샵", "펫샵.*입양", "유기견.*펫샵", "펫샵.*유기견",
      # 결혼/거주 상태
      "혼자.*아내", "아내.*혼자", "결혼.*모순",
      "기혼.*독거", "독거.*기혼",
      # 전공/직업
      "전공.*바뀌", "전공.*다른",
      # 기타 물리 속성
      "왼.*오른", "오른.*왼",
      "Ǯ.*하프", "하프.*풀", "풀코스.*하프"],
     "TRAIT_SETTING"),
]

# Soft 판정 키워드 — 이 패턴이 포함되면 SOFT, 나머지는 HARD
# (전체 expectation 분석 결과: 91%가 HARD이므로 SOFT를 특정하는 방식이 정확)
SOFT_PATTERNS = [
    # 약한 모순 (원문에 명시)
    r"약한 모순",
    # 감정 변화 (트리거 없는 급변)
    r"갑자기.*감정", r"갑자기.*적의", r"갑자기.*신뢰", r"갑자기.*해소",
    r"경계심.*해소", r"불신.*신뢰",
    # 판단력 저하 상태에서의 진술
    r"판단력.*저하", r"저혈당.*판단", r"약물.*판단",
    # 공식 채널 위반 (조직 내규 수준, 금지 아닌 것만)
    r"개인.*DM", r"개인 통화",
    # 경미한 신체 제약 위반 (부분적 가능)
    r"색맹.*판독", r"발목.*염좌.*이동", r"손.*떨림.*시술",
    # 맥락상 모호
    r"직접.*모순.*아니", r"직접적 모순은 아니",
]


def classify_category(text: str) -> str:
    """텍스트에서 모순 카테고리 자동 분류."""
    for keywords, category in CATEGORY_RULES:
        for kw in keywords:
            if re.search(kw, text):
                return category
    return "TRAIT_SETTING"  # 기본값


def classify_hard_soft(text: str) -> str:
    """Hard/Soft 판정. SOFT 패턴에 매칭되면 SOFT, 나머지는 HARD."""
    for pattern in SOFT_PATTERNS:
        if re.search(pattern, text):
            return "SOFT"
    return "HARD"


def extract_keywords(text: str) -> List[str]:
    """설명 텍스트에서 매칭용 키워드 추출."""
    # 따옴표 안의 텍스트 추출
    quoted = re.findall(r'["\u201c\u201d]([^"\u201c\u201d]+)["\u201c\u201d]', text)
    # 따옴표 안 텍스트에서 핵심 단어 추출
    keywords = []
    for q in quoted:
        words = [w for w in q.split() if len(w) >= 2]
        keywords.extend(words[:3])

    # 핵심 명사/구문 패턴 추출
    noun_patterns = [
        r'(\d+분)', r'(\d+시)', r'(\d+살)', r'(\d+년)',
        r'(\d+명)', r'(\d+개)', r'(\d+번)',
    ]
    for pat in noun_patterns:
        for m in re.findall(pat, text):
            keywords.append(m)

    # 핵심 키워드 직접 추출
    important_words = [
        "사망", "시체", "재등장", "봉쇄", "잠금", "열쇠", "카드", "마스터키",
        "우주복", "커피", "혐오", "마시", "습관", "설정", "견종", "고양이",
        "날씨", "비", "맑은", "노을", "보름달", "그믐", "의족",
        "입양", "펫샵", "유기견", "결혼", "혼자", "아내",
        "텔레포트", "순간이동", "마법", "봉인", "통신", "블랙아웃",
        "삼점슛", "레이업", "MVP", "승리", "패배",
    ]
    for w in important_words:
        if w in text:
            keywords.append(w)

    # 중복 제거 + 최대 8개
    seen = set()
    unique = []
    for k in keywords:
        if k not in seen:
            seen.add(k)
            unique.append(k)
    return unique[:8]


def extract_characters(text: str, case_text: str = "") -> List[str]:
    """텍스트에서 캐릭터 이름 추출 (간단한 휴리스틱)."""
    # 한국 이름 패턴 (2~3글자)
    names = re.findall(r'([가-힣]{2,3})(?:이|가|은|는|의|를|에게|와|과|한테)', text)
    # 중복 제거
    seen = set()
    unique = []
    for n in names:
        if n not in seen and n not in ("이것", "그것", "저것", "여기", "거기"):
            seen.add(n)
            unique.append(n)
    return unique[:4]


# ── 테스트 셋 정의 ──────────────────────────────────────────────

TESTSETS = [
    # (set_name, data_dir, file_pattern, genre)
    # 단일 파일 케이스
    ("case500", "case500", [
        ("case1", "case1.txt", "expectation1.txt", "일상"),
        ("case2", "case2.txt", "expectation2.txt", "일상"),
        ("case3", "case3.txt", "expectation3.txt", "일상"),
        ("case4", "case4.txt", "expectation4.txt", "일상"),
    ]),
    ("case1000", "case1000", [
        ("case5", "case5.txt", "expectation5.txt", "가족/사회"),
        ("case6", "case6.txt", "expectation6.txt", "가족/사회"),
        ("case7", "case7.txt", "expectation7.txt", "가족/사회"),
        ("case8", "case8.txt", "expectation8.txt", "가족/사회"),
    ]),
    ("case1000v2", "case1000v2", [
        ("case13", "case13.txt", "expectation13.txt", "사교/오락"),
        ("case14", "case14.txt", "expectation14.txt", "일상/반려동물"),
        ("case15", "case15.txt", "expectation15.txt", "여행"),
        ("case16", "case16.txt", "expectation16.txt", "스포츠"),
    ]),
    ("case2000", "case2000", [
        ("case9", "case9.txt", "expectation9.txt", "여행/기념일"),
        ("case10", "case10.txt", "expectation10.txt", "예술/전시"),
        ("case11", "case11.txt", "expectation11.txt", "가족/여행"),
        ("case12", "case12.txt", "expectation12.txt", "가족/문화"),
    ]),
    ("wss500", "wss500", [
        ("case17", "case17.txt", "expectation17.txt", "SF/우주"),
        ("case18", "case18.txt", "expectation18.txt", "사극/추리"),
        ("case19", "case19.txt", "expectation19.txt", "추리"),
        ("case20", "case20.txt", "expectation20.txt", "판타지"),
    ]),
    ("wss1000", "wss1000", [
        ("case21", "case21.txt", "expectation21.txt", "SF/사이버펑크"),
        ("case22", "case22.txt", "expectation22.txt", "무협"),
        ("case23", "case23.txt", "expectation23.txt", "첩보/스파이"),
        ("case24", "case24.txt", "expectation24.txt", "SF/해양"),
    ]),
    ("wss2_1000", "wss2_1000", [
        ("case25", "case25.txt", "expectation25.txt", "SF/시설"),
        ("case26", "case26.txt", "expectation26.txt", "판타지/SF"),
        ("case27", "case27.txt", "expectation27.txt", "서바이벌"),
        ("case28", "case28.txt", "expectation28.txt", "판타지/액션"),
    ]),
]

# 3파일 분리 케이스
TESTSETS_MULTI = [
    ("batch", "batch", [
        ("batch_1", "테스트 데이터 01", "테스트 데이터 01 기대값.txt", "SF/시설"),
        ("batch_2", "테스트 데이터 02", "테스트 데이터 02 기대값.txt", "판타지/궁중"),
        ("batch_3", "테스트 데이터 03", "테스트 데이터 03 기대값.txt", "SF/해저"),
        ("batch_4", "테스트 데이터 04", "테스트 데이터 04 기대값.txt", "SF/시간"),
    ]),
    ("long_case", "long_case", [
        ("long_9", "test_9", "test_9_expectation.txt", "SF/시설"),
        ("long_10", "test_10", "test_10_expectation.txt", "SF/시설"),
        ("long_11", "test_11", "test_11_expectation.txt", "SF/시설"),
        ("long_12", "test_12", "test_12_expectation.txt", "SF/시설"),
    ]),
    ("case2", "case2", [
        ("cases2_1", "test_1", "test_1_expectation.txt", "교도소/스릴러"),
        ("cases2_2", "test_2", "test_2_expectation.txt", "SF/첩보"),
        ("cases2_3", "test_3", "test_3_expectation.txt", "사극/수도원"),
        ("cases2_4", "test_4", "test_4_expectation.txt", "군사/전쟁"),
        ("cases2_5", "test_5", "test_5_expectation.txt", "의료/병원"),
        ("cases2_6", "test_6", "test_6_expectation.txt", "법정/재판"),
        ("cases2_7", "test_7", "test_7_expectation.txt", "SF/우주정거장"),
        ("cases2_8", "test_8", "test_8_expectation.txt", "의료/연구소"),
    ]),
    ("cases3", "cases3", [
        ("cases3_c500_13", "test_c500_13", "test_c500_13_expectation.txt", "사극/궁중"),
        ("cases3_c500_14", "test_c500_14", "test_c500_14_expectation.txt", "추리/등대"),
        ("cases3_c500_15", "test_c500_15", "test_c500_15_expectation.txt", "의료/병원"),
        ("cases3_c500_16", "test_c500_16", "test_c500_16_expectation.txt", "군사/전쟁"),
        ("cases3_c1000_17", "test_c1000_17", "test_c1000_17_expectation.txt", "추리/법정"),
        ("cases3_c1000_18", "test_c1000_18", "test_c1000_18_expectation.txt", "사극/궁중"),
        ("cases3_c1000_19", "test_c1000_19", "test_c1000_19_expectation.txt", "의료/병원"),
        ("cases3_c1000_20", "test_c1000_20", "test_c1000_20_expectation.txt", "SF/시설"),
    ]),
]

# wss4000 케이스 (3파일 분리지만 expectation은 단일 파일)
TESTSETS_WSS4000 = [
    ("wss4000", "wss4000", [
        ("case29", "case29", "expectation29.txt", "추리/범죄"),
        ("case30", "case30", "expectation30.txt", "판타지/중세"),
        ("case31", "case31", "expectation31.txt", "의료/병원"),
        ("case32", "case32", "expectation32.txt", "SF/항해"),
    ]),
]

# variation 케이스는 기존 gold_standard.py에 있으므로 제외


def parse_expectation(filepath: str) -> List[Tuple[str, int]]:
    """expectation 파일 파싱. (설명, 번호) 리스트 반환.

    두 가지 형식을 모두 처리:
    형식 A (1줄 = 1모순): "1. 설명 전체가 한 줄"
    형식 B (번호 + 하위줄):
        1. 성격/설정 모순 (Hard)
        - 설정: ...
        - 시나리오: ...
    → 하위줄("-"로 시작)을 번호 줄에 병합하여 1건으로 처리.
    헤더([기대되는...]), 푸터([기대 모순 개수], - 총 N건) 줄은 제거.
    """
    if not os.path.exists(filepath):
        return []
    with open(filepath, encoding="utf-8") as f:
        text = f.read()

    # 헤더/푸터 필터용 패턴
    skip_patterns = [
        r'^\[기대되는',
        r'^\[기대 모순',
        r'^-\s*총\s*\d+건',
        r'^\ufeff?\[기대',       # BOM + 헤더
    ]

    lines = text.strip().split("\n")
    results = []
    current_num = 0
    current_text = ""

    def flush():
        nonlocal current_text, current_num
        if current_text.strip():
            results.append((current_text.strip(), current_num))
        current_text = ""
        current_num = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 헤더/푸터 스킵
        if any(re.match(p, line) for p in skip_patterns):
            continue

        # 번호 줄: "1. ..."
        m = re.match(r'^(\d+)\.\s*(.+)', line)
        if m:
            flush()
            current_num = int(m.group(1))
            current_text = m.group(2).strip()
        elif line.startswith("-") and current_num > 0:
            # 하위 줄: "- 설정: ...", "- 시나리오: ..." → 현재 항목에 병합
            sub = line.lstrip("-").strip()
            current_text += " " + sub
        else:
            # 번호 없는 독립 줄 (batch 형식: "물리 규칙 (Hard): 설명")
            flush()
            current_num = len(results) + 1
            current_text = line

    flush()
    return results


def generate_gold_entry(
    case_name: str, idx: int, description: str
) -> dict:
    """단일 모순 → Gold 엔트리."""
    return {
        "id": f"{case_name}-{idx}",
        "category": classify_category(description),
        "hard_soft": classify_hard_soft(description),
        "description": description,
        "characters": extract_characters(description),
        "keywords": extract_keywords(description),
    }


def main():
    base_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data", "sample"
    )

    all_cases = []

    # 단일 파일 케이스
    for set_name, data_dir, cases in TESTSETS:
        for case_name, case_file, exp_file, genre in cases:
            exp_path = os.path.join(base_dir, data_dir, exp_file)
            entries = parse_expectation(exp_path)
            if not entries:
                print(f"  SKIP: {exp_path} (not found or empty)", file=sys.stderr)
                continue

            contradictions = []
            for desc, idx in entries:
                contradictions.append(generate_gold_entry(case_name, idx, desc))

            all_cases.append({
                "name": case_name,
                "set": set_name,
                "genre": genre,
                "data_dir": data_dir,
                "case_file": case_file,
                "exp_file": exp_file,
                "format": "single",
                "contradictions": contradictions,
            })

    # 3파일 분리 케이스
    for set_name, data_dir, cases in TESTSETS_MULTI + TESTSETS_WSS4000:
        for case_name, case_prefix, exp_file, genre in cases:
            exp_path = os.path.join(base_dir, data_dir, exp_file)
            entries = parse_expectation(exp_path)
            if not entries:
                print(f"  SKIP: {exp_path} (not found or empty)", file=sys.stderr)
                continue

            contradictions = []
            for desc, idx in entries:
                contradictions.append(generate_gold_entry(case_name, idx, desc))

            all_cases.append({
                "name": case_name,
                "set": set_name,
                "genre": genre,
                "data_dir": data_dir,
                "case_prefix": case_prefix,
                "exp_file": exp_file,
                "format": "multi",
                "contradictions": contradictions,
            })

    # 통계 출력
    total_contradictions = sum(len(c["contradictions"]) for c in all_cases)
    print(f"\n=== Gold Standard 생성 완료 ===", file=sys.stderr)
    print(f"총 {len(all_cases)}개 케이스, {total_contradictions}건 모순", file=sys.stderr)

    # 카테고리별 집계
    cat_counts = {}
    hs_counts = {"HARD": 0, "SOFT": 0}
    for c in all_cases:
        for con in c["contradictions"]:
            cat_counts[con["category"]] = cat_counts.get(con["category"], 0) + 1
            hs_counts[con["hard_soft"]] = hs_counts.get(con["hard_soft"], 0) + 1

    print(f"\n카테고리별:", file=sys.stderr)
    for cat, cnt in sorted(cat_counts.items(), key=lambda x: -x[1]):
        print(f"  {cat:20s}: {cnt}", file=sys.stderr)
    print(f"\nHard/Soft:", file=sys.stderr)
    for hs, cnt in hs_counts.items():
        print(f"  {hs}: {cnt}", file=sys.stderr)

    # JSON 출력
    output_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "gold_standard_cases.json"
    )
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_cases, f, ensure_ascii=False, indent=2)
    print(f"\n출력: {output_path}", file=sys.stderr)

    # 셋별 요약 테이블
    print(f"\n{'세트':12s} {'케이스':6s} {'모순':6s} {'HARD':6s} {'SOFT':6s}", file=sys.stderr)
    print("─" * 40, file=sys.stderr)
    for set_name in dict.fromkeys(c["set"] for c in all_cases):
        set_cases = [c for c in all_cases if c["set"] == set_name]
        n_cases = len(set_cases)
        n_con = sum(len(c["contradictions"]) for c in set_cases)
        n_hard = sum(1 for c in set_cases for con in c["contradictions"] if con["hard_soft"] == "HARD")
        n_soft = n_con - n_hard
        print(f"{set_name:12s} {n_cases:6d} {n_con:6d} {n_hard:6d} {n_soft:6d}", file=sys.stderr)


if __name__ == "__main__":
    main()
