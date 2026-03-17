# ContiCheck - 시나리오 정합성 검증 시스템 POC

## 프로젝트 개요
드라마/영화/게임/소설 시나리오의 모순을 자동으로 탐지하는 시스템.
7가지 모순 유형. 의도성 판단은 사용자에게 위임.

## 5계층 아키텍처
1. Extraction: 텍스트 → RawEntity
2. Normalization: RawEntity → NormalizedEntity (통합/병합/충돌감지)
3. Graph Materialization: NormalizedEntity → Vertex/Edge (DB 적재)
4. Contradiction Detection: 그래프 → 7가지 쿼리 → 모순 리포트
5. Review Workflow: 사용자 확인 → 그래프 피드백 → 재탐지 → 버전 관리

## 핵심 워크플로우
1) 3분류 업로드 (세계관/설정집/시나리오) → 2트랙 GraphRAG 구축
2) 모순 탐지: 확실한 모순=자동, 애매한 케이스=사용자 확인(원본 발췌 필수)
3) 수정 반영: 스테이징 → Push → 원본 업데이트 → GraphRAG 재구축 → 버전 관리

## 기술 스택
- Backend: Python 3.12, FastAPI, LangGraph
- Frontend: React 18 + TypeScript + Tailwind CSS
- Database: Azure Cosmos DB (Gremlin API)
- Search: Azure AI Search
- LLM: Azure Foundry (GPT-5-nano 추출, Claude Opus 4.6 추론)
- 인프라: Azure 전체

## 온톨로지 (9노드 + 13엣지)
Vertices: Character, KnowledgeFact, Event, Trait, Organization,
          Location, Item, Source, UserConfirmation
Edges: LEARNS, MENTIONS, PARTICIPATES_IN, HAS_STATUS, AT_LOCATION,
       RELATED_TO, BELONGS_TO, FEELS, HAS_TRAIT, VIOLATES_TRAIT,
       POSSESSES, LOSES, SOURCED_FROM

## 데이터 소스 분류
- worldview: 세계관
- settings: 설정집
- scenario: 시나리오
- manuscript: 검증 대상 신규 원고

## 디렉토리 구조
```
conticheck/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── models/
│   │   │   ├── vertices.py      # 9 Vertex 모델
│   │   │   ├── edges.py         # 13 Edge 모델
│   │   │   ├── enums.py         # 열거형 + 기반 클래스
│   │   │   ├── intermediate.py  # RawEntity, NormalizedEntity
│   │   │   └── api.py           # API 입출력 모델
│   │   ├── services/
│   │   │   ├── ingest.py        # 문서 파싱 + 청킹
│   │   │   ├── extraction.py    # 계층1: LLM 원시 추출
│   │   │   ├── normalization.py # 계층2: 정규화/통합
│   │   │   ├── graph.py         # 계층3: Cosmos DB 연동
│   │   │   ├── detection.py     # 계층4: 모순 탐지
│   │   │   ├── confirmation.py  # 계층5: 사용자 확인 관리
│   │   │   ├── version.py       # 계층5: 버전 관리
│   │   │   ├── search.py        # Azure AI Search
│   │   │   └── agent.py         # LangGraph 오케스트레이터
│   │   └── prompts/
│   ├── tests/
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   └── api/
│   └── package.json
├── data/sample/
├── docs/ontology-schema.md
└── README.md
```

## 코딩 컨벤션
- Python: 타입 힌트 필수, async/await 사용
- 환경변수: .env 파일
- 에러 처리: try/except + 재시도
- 로깅: structlog