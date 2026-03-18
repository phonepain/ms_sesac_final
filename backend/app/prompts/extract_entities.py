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
다음 지침에 따라 추출하세요.

[추출 대상]
1. 장면/이벤트 (설명, 장소) -> events
2. 대화를 통해 알게 된 정보 (누가 무엇을 들었는지/언급했는지) -> knowledge_events
3. 아이템의 획득/분실 -> item_events
    (action 값은 반드시 아래 3개 중 하나만 사용하세요:
    - "possesses" : 새로 획득
    - "loses" : 잃어버림
    - "uses" : 사용)
    예시:
    {
    "character_name": "철수",
    "item_name": "권총",
    "action": "possesses"
    }
4. 등장 캐릭터 -> characters


입력 텍스트:
{text}
"""