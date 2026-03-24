# backend/app/prompts/extract_entities.py

WORLDVIEW_PROMPT = """
이 텍스트는 서사 작품의 '세계관 설정'입니다.
다음 지침에 따라 추출하세요.

[추출 대상]
1. 세계 규칙/법칙/역사 -> facts (category_hint: "world_fact")
    ★ 특히 다음 패턴은 반드시 별도의 fact로 추출하세요:
    - 이동 시간/거리 제약: "A에서 B까지 N분 소요" 형태로 정확히 기술
      예시: {{"content": "본관에서 별채까지 지하 통로로 도보 15분 소요", "category_hint": "world_fact"}}
    - 시간 기반 봉쇄/통제: "N시 이후 ~봉쇄/잠금/출입금지"
      예시: {{"content": "22시 이후 전관 락다운, 모든 문이 물리적으로 잠긴다", "category_hint": "world_fact"}}
    - 물리적 제약/금지: "~없이는 ~할 수 없다", "~이 불가능하다"
      예시: {{"content": "우주복 없이는 30초 이상 생존할 수 없다", "category_hint": "world_fact"}}
    - 통신/기술 제한: "N시~N시 통신 불가", "~구간에서 ~이 봉쇄된다"
      예시: {{"content": "00:00~04:00 시 전역 네트워크 블랙아웃으로 외부 통신 차단", "category_hint": "world_fact"}}
    - 고유/유일 아이템: "단 하나뿐", "유일한"
    - 인증/보안 규칙: "생체 인증 필요", "양도 불가"
2. 장소 이름, 유형 -> events의 location_hint 등에 활용
3. 조직/세력 이름 -> facts나 traits로 추출

입력 텍스트:
{text}
"""

SETTINGS_PROMPT = """
이 텍스트는 서사 작품의 '캐릭터 설정집'입니다.
다음 지침에 따라 추출하세요.

[추출 대상]
1. 캐릭터 (이름, 별명, 역할) -> characters
2. 특성 (성격, 외모, 능력 등) -> traits
    ★ 특히 다음 패턴은 반드시 trait로 추출하세요:
    - 금지/불가 습관: "절대 ~하지 않는다", "~을 극도로 혐오", "입에 대지 않는다"
      예시: {{"character_name": "A", "key": "습관", "value": "커피를 극도로 혐오하며 절대 마시지 않음", "category_hint": "preference"}}
      예시: {{"character_name": "B", "key": "체질", "value": "카페인 일절 섭취하지 않음", "category_hint": "preference"}}
      예시: {{"character_name": "C", "key": "습관", "value": "술을 입에 대지 않음", "category_hint": "preference"}}
    - 신체/능력 제한: "~할 수 없다", "~이 불가능하다", "과민반응"
      예시: {{"character_name": "A", "key": "체질", "value": "신경 임플란트 사용 불가", "category_hint": "physical"}}
    - 사망 상태: "사망", "죽음", "사망 판정", "처형", "사망 처리", "시체로 발견"
      예시: {{"character_name": "A", "key": "상태", "value": "3년 전 처형으로 사망", "category_hint": "background"}}
    - 불변 습관/규칙: "절대", "결코", "반드시", "항상"
      예시: {{"character_name": "A", "key": "습관", "value": "기록을 절대 누락하지 않음", "category_hint": "personality"}}
3. 관계 (두 캐릭터 간 관계 유형) -> relationships
    type_hint는 반드시 아래 영문 값 중 하나로 지정하세요:
    - "family_parent"   : 부모-자녀 (어머니, 아버지, 아들, 딸)
    - "family_sibling"  : 형제자매 (형, 누나, 오빠, 언니, 남매)
    - "family_spouse"   : 배우자 (남편, 아내)
    - "romantic"        : 연인
    - "friend"          : 친구
    - "colleague"       : 동료, 동기, 파트너
    - "rival"           : 라이벌, 경쟁자
    - "enemy"           : 적, 원수, 숙적
    - "mentor_student"  : 스승-제자
    - "master_servant"  : 주인-하인
    예시: {{"char_a": "A", "char_b": "B", "type_hint": "family_parent", "detail": "어머니"}}
    ★ 한 캐릭터 쌍에 대해 여러 관계가 기술된 경우 각각 별도 항목으로 추출하세요.
4. 소유물 (아이템 이름) -> item_events (초기 소유 상태)

입력 텍스트:
{text}
"""

SCENARIO_PROMPT = """
이 텍스트는 서사 작품의 '시나리오/대본'입니다.
세계관·캐릭터 설정이 함께 포함된 경우에도 아래 모든 항목을 추출하세요.

[추출 대상]
1. 장면/이벤트 (설명, 장소) -> events
    events의 event_type은 반드시 아래 값 중 하나로 지정하세요:
    - "scene"           : 일반 장면
    - "death"           : 캐릭터 사망. status_char에 사망한 캐릭터 이름을 반드시 기입하세요.
    - "location_change" : 캐릭터 위치 이동
    - "status_change"   : 캐릭터 상태 변화
    사망 장면 예시 (캐릭터가 죽거나, 시체로 발견되거나, 사망이 확인되는 모든 장면):
    {{"description": "박영호가 총에 맞아 사망했다", "event_type": "death", "status_char": "박영호",
      "characters_involved": ["박영호", "강진우"], "location_hint": "골목"}}
    ★ 이벤트 description 작성 시 반드시 포함할 것:
    - 캐릭터가 음식/음료를 먹거나 마시는 행동 (예: "강진우가 커피를 마신다")
    - 장면 헤더에 명시된 시각 정보 (예: "오후 9시 5분에 실험실에 도착")
    - 이동에 소요된 구체적 시간 (예: "5분 만에 별채에 도착") — 대사에서도 추출
    - 이동 경로/거리 관련 수치 (예: "지하 통로로 5분 만에 이동")
    - "~없이" 행동: 필수 장비/아이템/자격 없이 행동하는 장면은
      반드시 "없이"를 포함하여 기술 (예: "카드 없이 문을 연다", "산소 슈트 없이 외부로 나간다")
    - 세계 규칙 위반 행동: 금지/불가능으로 명시된 행동을 캐릭터가 수행하는 장면은
      그 행동을 구체적으로 기술 (예: "심해에서 통신기로 실시간 화상 통화를 시도한다")
2. 정보 흐름 -> knowledge_events
    각 항목의 event_type을 반드시 아래 둘 중 하나로 지정하세요:
    - "mentions" : 캐릭터가 이미 알고 있는 사실을 대사/행동으로 표현하는 경우
    - "learns"   : 캐릭터가 처음으로 어떤 사실을 알게 되는 경우
                   (진술 청취, 목격, 증거 확인, 타인에게 전달받음 등)
    fact_content는 캐릭터가 언급/학습한 사실을 짧고 정규화된 형태로 기술하세요.
    예시:
    {{"character_name": "A", "fact_content": "범인은 B이다", "event_type": "mentions",
      "method": "direct_speech", "via_character": null, "dialogue_text": "B가 범인이야"}}
    {{"character_name": "A", "fact_content": "범인은 B이다", "event_type": "learns",
      "method": "testimony", "via_character": "C", "dialogue_text": "C의 진술 확인"}}
    ★ 정보 비대칭 핵심 패턴 — 반드시 추출:
    - "~전에 알고 있었다", "이미 알고 있었지", "~전부터 알고 있었어"
      → 해당 캐릭터의 mentions를 추출 + 다른 캐릭터가 실제로 인지한 시점의 learns도 추출
      예시: A가 "나는 22시부터 알고 있었어"라고 말하고, B가 23시에 처음 발견했다면:
      {{"character_name": "A", "fact_content": "B의 열쇠 분실", "event_type": "mentions",
        "method": "direct_speech", "via_character": null, "dialogue_text": "나는 22시부터 알고 있었어"}}
      {{"character_name": "B", "fact_content": "B의 열쇠 분실", "event_type": "learns",
        "method": "observation", "via_character": null, "dialogue_text": "열쇠가 없어졌다"}}
    주의: 같은 사실에 대해 mentions(앞)와 learns(뒤)가 모두 추출되면 정보 비대칭 모순을 탐지할 수 있습니다.
3. 아이템의 획득/분실 -> item_events
    (action 값은 반드시 아래 3개 중 하나만 사용하세요:
    - "possesses" : 새로 획득
    - "loses" : 잃어버림
    - "uses" : 사용)
    예시:
    {{
      "character_name": "철수",
      "item_name": "권총",
      "action": "possesses"
    }}
4. 등장 캐릭터 (이름, 별명, 역할) -> characters
5. 캐릭터 특성 (성격, 직업, 능력 등 key-value) -> traits
    예시: {{"character_name": "철수", "key": "직업", "value": "형사", "category_hint": "background"}}
6. 캐릭터 간 관계 -> relationships
    예시: {{"char_a": "철수", "char_b": "영희", "type_hint": "colleague", "detail": "파트너"}}
7. 감정 상태 (누가 누구에게 어떤 감정) -> emotions
    예시: {{"from_char": "철수", "to_char": "영희", "emotion": "trust", "trigger_hint": null}}

입력 텍스트:
{text}
"""