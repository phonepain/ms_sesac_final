CONTRADICTION_PROMPT = """
당신은 서사 작품의 설정 모순을 검증하는 전문가입니다.
지식 그래프 또는 쿼리 엔진에서 발견된 '모순 후보'를 분석하여, 이것이 실제로 모순(Hard Contradiction)인지, 아니면 의도된 미스테리나 착오(Soft Inconsistency/Foreshadowing)인지 판별하세요.

[입력 데이터]
{violation_data}

[판별 기준]
1. Confidence: 0.0 ~ 1.0 (0.8 이상이면 명백한 모순으로 간주)
2. Reasoning: 왜 이것이 모순인지, 혹은 왜 모순이 아닐 수 있는지에 대한 논리적 근거
3. User Question: 모순이 아닐 가능성이 있을 때 사용자에게 확인할 질문

[출력 형식]
{{
  "confidence": 0.9,
  "reasoning": "캐릭터 A는 Scene 1에서 사망했음에도 불구하고 Scene 3에서 대사를 하고 있습니다. 이는 명백한 설정 오류입니다.",
  "user_question": null
}}
"""