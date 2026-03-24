# backend/app/prompts/extract_entities.py

WORLDVIEW_PROMPT = """
이 텍스트는 서사 작품의 '세계관 설정'입니다.
다음 지침에 따라 추출하세요.

[추출 대상]
1. 세계 규칙/법칙/역사 -> facts (category_hint: "world_fact")
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
3. 관계 (두 캐릭터 간 관계 유형) -> relationships
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
    - 장면 헤더에 명시된 시각 정보 (예: "오후 11시 10분에 별채에 도착")
    - 이동에 소요된 구체적 시간 (예: "5분 만에 별채에 도착") — 대사에서도 추출
    - 이동 경로/거리 관련 수치 (예: "지하 통로로 5분 만에 이동")
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