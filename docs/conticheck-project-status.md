# ContiCheck 프로젝트 진행 상황

> **최종 업데이트**: 2026-03-14  
> **목적**: 세션 간 일관성 유지를 위한 프로젝트 전체 상태 추적  
> **사용법**: 새 세션을 시작할 때 이 문서와 함께 관련 산출물을 첨부하세요

---

## 1. 프로젝트 개요

**ContiCheck**는 드라마/영화/게임/소설 시나리오의 설정 오류를 AI가 자동으로 탐지하는 시스템입니다.

### 핵심 워크플로우

```
[1단계: 지식 베이스 구축]
  사용자가 세계관/설정집/시나리오를 분류하여 TXT/PDF 업로드
  → 2트랙 GraphRAG 구축:
    트랙 A: 세계관 + 설정집 → 세계관·설정 그래프
    트랙 B: 시나리오 → 시나리오 그래프

[2단계: 모순 탐지]
  지식 베이스와 대조하여 7가지 모순 유형 탐지
  → 확실한 모순은 자동 판정
  → 애매한 케이스는 사용자 확인 요청 (원본 발췌 함께 표시)

[3단계: 수정 반영]
  모순 수정 → 스테이징(Commit) → 일괄 반영(Push)
  → 원본 자동 업데이트 → GraphRAG 재구축 → 버전 관리
```

### 탐지하는 모순 7가지

| # | 유형 | 설명 |
|---|------|------|
| 1 | 정보 비대칭 | 캐릭터가 아직 모르는 정보를 언급 |
| 2 | 타임라인 | 사망 후 등장, 동시 존재 불가, 비현실적 이동, 환경 제약 위반 |
| 3 | 관계 | 관계 설정 충돌, 추이 불일치, 조직 소속 충돌 |
| 4 | 성격·설정 | 확립된 설정과 행동 불일치 |
| 5 | 감정 일관성 | 이벤트 없는 감정 급변, 감정-행동 불일치 |
| 6 | 소유물 추적 | 유일 아이템 중복 소유, 상실 후 사용, 접근 권한 위반 |
| 7 | 거짓말·기만 | 거짓 정보 기반 행동, 진실 인지 후에도 속은 상태로 행동 |

### 시스템 5계층 아키텍처

```
┌─────────────────────────────────────────────────┐
│ 1. Extraction        원시 추출                    │
│    텍스트 → RawEntity (이름, 문장, 패턴 수준)      │
├─────────────────────────────────────────────────┤
│ 2. Normalization     정규화/통합                   │
│    RawEntity → NormalizedEntity                  │
│    동일 캐릭터 통합, 동일 사실 병합, 소스 충돌 감지  │
├─────────────────────────────────────────────────┤
│ 3. Graph Materialization   그래프 구체화          │
│    NormalizedEntity → Vertex/Edge                │
│    discourse_order/story_order 부여, DB 적재       │
├─────────────────────────────────────────────────┤
│ 4. Contradiction Detection   모순 탐지            │
│    완성된 그래프 → 7가지 쿼리 → 모순 리포트         │
│    구조적 자동 판정 + LLM 보조 (confidence≥0.8)    │
├─────────────────────────────────────────────────┤
│ 5. Review Workflow   사용자 확인 + 수정 반영       │
│    UserConfirmation → 사용자 응답                 │
│    → 3단계로 피드백 (그래프 업데이트)               │
│    → 4단계 재탐지                                │
│    스테이징 → Push → 버전 관리                     │
└─────────────────────────────────────────────────┘
```

계층 분리의 목적: 각 단계의 입력/출력이 명확하여 **어느 계층에서 문제가 생겼는지** 바로 식별 가능

| 문제 상황 | 원인 계층 |
|----------|----------|
| 캐릭터 이름을 못 잡음 | 1. Extraction |
| 같은 캐릭터가 2개로 등록됨 | 2. Normalization |
| story_order가 꼬임 | 3. Materialization |
| 모순인데 못 잡음 | 4. Detection |
| 사용자 확인 후 재분석 안 됨 | 5. Review |

### 기술 스택

| 영역 | 기술 |
|------|------|
| Backend | Python 3.12, FastAPI, LangGraph |
| Frontend | React 18 + TypeScript + Tailwind CSS |
| Database | Azure Cosmos DB (Gremlin API) — 지식 그래프 |
| Search | Azure AI Search — 벡터 + 키워드 하이브리드 |
| LLM | Azure Foundry (GPT-5-nano 추출용, Claude Opus 4.6 추론용) |
| Infra | Azure 전체 |

---

## 2. 완료된 작업 (설계 단계)

현재 **설계 단계가 완료**되었으며, 구현(백엔드/프론트엔드 코드)은 아직 시작하지 않았습니다.

### ✅ 2-1. 프론트엔드 UI 프로토타입 (v3)

**파일**: `conticheck-v3.html`

구현된 기능:
- **좌측 사이드바**: 프로젝트 목록 (채팅 앱 형태), 새 프로젝트 버튼
- **프로젝트 선택 시**: KB 통계 카드 + 등록 소스 + 모순 알림 즉시 표시
- **3탭 구조**: 개요 / 모순 / 버전
- **3분류 업로드**: 세계관(🌍) / 설정집(📋) / 시나리오(🎬)
- **2트랙 GraphRAG 구축**: 세계관+설정집 트랙 / 시나리오 트랙 분리
- **온보딩 가이드**: 시나리오만/세계관+설정집만/전체(권장) 3모드 안내
- **모순 수정 → 스테이징 → Push**: git commit+push 방식
- **Push 후 GraphRAG 재구축**: 진행 오버레이
- **버전 관리 페이지**: 타임라인 수정 이력
- **AI 질의**: 그라데이션 버튼, 2컬럼 분할 채팅 패널

제거된 기능: 위키 크롤링 전면 제거

### ✅ 2-2. 온톨로지 설계 문서 (v2.2)

**파일**: `conticheck-ontology-schema.md` (1,418줄)

온톨로지 구성:
- **9 Vertices**: Character, KnowledgeFact, Event, Trait, Organization, Location, Item, Source, UserConfirmation
- **13 Edges**: LEARNS, MENTIONS, PARTICIPATES_IN, HAS_STATUS, AT_LOCATION, RELATED_TO, BELONGS_TO, FEELS, HAS_TRAIT, VIOLATES_TRAIT, POSSESSES, LOSES, SOURCED_FROM
- **7 모순 유형**: 정보 비대칭, 타임라인, 관계, 성격·설정, 감정 일관성, 소유물 추적, 거짓말·기만
- **9 사용자 확인 유형**: flashback_check, intentional_change, foreshadowing, source_conflict, emotion_shift, relationship_ambiguity, item_discrepancy, timeline_ambiguity, unreliable_narrator

v2.2 핵심 설계:
- **[v2.2] 이중 시간 축**: discourse_order(텍스트 등장 순서) + story_order(서사 세계 실제 시점, null 가능) → 회상/비선형 서사를 예외 분기 없이 처리. is_flashback/flashback_target_order 제거.
- **[v2.2] Hard/Soft 형식 구분**: Hard Contradiction(논리적 불가능, 자동 판정) vs Soft Inconsistency(맥락에 따라 의도적, 사용자 확인). 판정 흐름: hard? → 자동 / LLM ≥0.8? → 자동 / 나머지 → UserConfirmation
- **[v2.2] 임시 그래프 격리**: analyze() 시 In-Memory 스냅샷으로 복제, 복제본에서만 작업, Push 시에만 canonical graph 업데이트
- Fact.is_true + LEARNS.believed_true → 거짓말·기만 추적
- Event.environment (시간/날씨/조명/특수조건) → 환경 제약 탐지
- Organization + BELONGS_TO → 세력/조직 소속 + 비밀 소속
- Trait.category에 goal/motivation 추가
- POSSESSES.possession_type (owns/holds/can_access/guards) → 소유·접근 권한 세분화
- Item.location_id → 아이템 위치 기반 모순
- KnowledgeFact vs Trait 구분 기준 명시 ("다른 캐릭터가 이걸 모를 수 있는가?")
- 의도성 판단은 사용자에게 위임 (LLM이 복선/의도 판단 안 함)
- 다중 소스 충돌 시 사용자가 정본 결정 (원본 나란히 표시)

### ✅ 2-3. 온톨로지 인터랙티브 다이어그램 (v2.2)

**파일**: `conticheck-ontology-diagram.html`

- 9노드 + 13엣지 캔버스 시각화
- 사이드바 4탭: 노드(9) / 엣지(13) / 확인유형(8) / 설계
- 엣지별 **HARD/SOFT 배지** 표시
- 설계 탭: 이중 시간 축, Hard/Soft 구분, 임시 그래프 격리, Truth vs Belief 설명
- Event 노드: discourse_order, story_order, is_linear 표시
- 범례에 "HARD = 자동 판정 / SOFT = 사용자 확인" 구분

### ✅ 2-4. Claude Code 구현 가이드

**파일**: `conticheck-claude-code-guide.md`

- Phase 0~9 단계별 Claude Code 지시 프롬프트 (5계층 아키텍처 기반)
- CLAUDE.md 템플릿, Pydantic 모델 정의 (v2.2 온톨로지 반영)
- 팀원별 사용 가이드 (온톨로지+DB, LLM추출, LLM탐지, 백엔드, 프론트)

---

## 3. 전체 산출물 목록

| # | 파일명 | 유형 | 버전 | 상태 | 용도 |
|---|--------|------|------|------|------|
| 1 | `conticheck-v3.html` | HTML | v3 | ✅ 완료 | 프론트엔드 프로토타입 |
| 2 | `conticheck-ontology-schema.md` | MD | v2.2 | ✅ 완료 | 온톨로지 설계 문서 |
| 3 | `conticheck-ontology-diagram.html` | HTML | v2.2 | ✅ 완료 | 온톨로지 시각화 |
| 4 | `conticheck-claude-code-guide.md` | MD | v2.2 | ✅ 완료 | Claude Code 구현 가이드 |
| 5 | `conticheck-project-status.md` | MD | - | ✅ 최신 | 이 문서 |

폐기된 파일:
- `conticheck-v2.html` — v2 프론트 (위키 포함, 사이드바 없음)
- `conticheck.html` — v1 프론트 (에피소드 기반)
- `conticheck-frontend.jsx` — v1 React 컴포넌트

---

## 4. 남은 작업

### ✅ 4-0. claude-code-guide 업데이트 (완료)

5계층 아키텍처 반영, v2.2 온톨로지 반영, 이중 시간 축, Hard/Soft, 그래프 격리 모두 반영됨.

### 🔲 4-1. Phase 0 — 프로젝트 스캐폴딩

| 작업 | 설명 | 담당 |
|------|------|------|
| Vite + React + TS 프로젝트 | v3 프로토타입 → 실제 프로젝트 | 프론트엔드 |
| FastAPI 앱 뼈대 | main.py, config.py | 백엔드 |
| Pydantic 모델 | 9노드 + 13엣지 + RawEntity + NormalizedEntity + API 모델 | 백엔드 |
| CLAUDE.md | 프로젝트 컨텍스트 파일 | 전체 |

### 🔲 4-2. Phase 1 — Extraction (계층 1)

| 작업 | 설명 | 담당 |
|------|------|------|
| IngestService | TXT/PDF 파싱 + 청킹 + 3분류 메타데이터 | 백엔드 |
| 추출 프롬프트 | 소스 분류별 전략 (세계관/설정집/시나리오) | LLM(추출) |
| ExtractionService | LLM 호출 → RawEntity 생성 | LLM(추출) |
| MockExtractionService | 하드코딩 결과 반환 | LLM(추출) |
| 추출 정확도 검증 | 테스트 데이터 대비 정확도 측정 | LLM(추출) |

### 🔲 4-3. Phase 2 — Normalization (계층 2)

| 작업 | 설명 | 담당 |
|------|------|------|
| NormalizationService | RawEntity → NormalizedEntity 변환 | 백엔드+LLM |
| 캐릭터 통합 | "형사 A" = "A" = "에이" 동일 캐릭터 판정 | LLM(추출) |
| 사실 병합 | "범인은 B이다" = "B가 살인을 저질렀다" 동일 사실 판정 | LLM(추출) |
| 다중 소스 충돌 감지 | 같은 사실이 소스별로 다를 때 → source_conflict 생성 | 백엔드 |
| Fact vs Trait 분류 | "다른 캐릭터가 모를 수 있는가?" 기준 자동 분류 | LLM(추출) |

### 🔲 4-4. Phase 3 — Graph Materialization (계층 3)

| 작업 | 설명 | 담당 |
|------|------|------|
| GremlinGraphService | 9노드 CRUD + 13엣지 + Cosmos DB 연동 | 온톨로지+DB |
| InMemoryGraphService | 동일 인터페이스 테스트 구현 | 온톨로지+DB |
| discourse_order/story_order 부여 | 이중 시간 축 규칙 + 비선형 서사 감지 + 소스 간 통합 | 온톨로지+DB |
| 그래프 적재 | NormalizedEntity → Vertex/Edge 변환 + DB 쓰기 | 온톨로지+DB |
| test_graph.py | 7모순 유형 + 사용자 확인 + 소스 삭제 테스트 | 온톨로지+DB |

### 🔲 4-5. Phase 4 — Contradiction Detection (계층 4)

| 작업 | 설명 | 담당 |
|------|------|------|
| DetectionService | 7가지 모순 쿼리 실행 | LLM(탐지) |
| 검증 프롬프트 | confidence≥0.8만 자동, 나머지 사용자 확인 | LLM(탐지) |
| 과거 회상 감지 | 서사 흐름 점프 → flashback_check | LLM(탐지) |
| 거짓말 탐지 | is_true + believed_true 기반 쿼리 | LLM(탐지) |
| 환경 제약 탐지 | Event.environment vs 행동 불일치 | LLM(탐지) |
| LangGraph 에이전트 | 계층 1~4 오케스트레이션 | LLM(탐지)+백엔드 |

### 🔲 4-6. Phase 5 — Review Workflow (계층 5)

| 작업 | 설명 | 담당 |
|------|------|------|
| ConfirmationService | 생성, 조회, 해결 + 그래프 피드백 루프 | 백엔드 |
| VersionService | 스테이징, Push, 원본 반영, 재구축 트리거 | 백엔드 |
| 피드백 루프 | 사용자 확인 → 3단계(그래프 업데이트) → 4단계(재탐지) | 백엔드 |

### 🔲 4-7. Phase 6 — Azure AI Search 연동

| 작업 | 설명 | 담당 |
|------|------|------|
| SearchService | 벡터+키워드 검색, 원본 발췌 추출 | 백엔드 |
| MockSearchService | 문자열 매칭 기반 | 백엔드 |

### 🔲 4-8. Phase 7 — FastAPI 엔드포인트

| 작업 | 설명 | 담당 |
|------|------|------|
| 소스 관리 API | upload(3분류), list, delete, stats | 백엔드 |
| GraphRAG 구축 API | build(2트랙), status | 백엔드 |
| 모순 탐지 API | analyze, scan | 백엔드 |
| 사용자 확인 API | list_pending, resolve | 백엔드 |
| 수정 반영 API | stage, push | 백엔드 |
| 버전 관리 API | list, get, diff | 백엔드 |
| AI 질의 API | GraphRAG 기반 LLM 질의 | 백엔드 |

### 🔲 4-9. Phase 8 — 프론트엔드 실제 구현

| 작업 | 설명 | 담당 |
|------|------|------|
| React 전환 | v3 프로토타입 → Vite+React+TS | 프론트엔드 |
| API 연동 | 전체 엔드포인트 연결 | 프론트엔드 |
| 사용자 확인 UI | 원본 나란히 표시, 응답, 해결 | 프론트엔드 |
| 버전 비교 UI | diff 표시 | 프론트엔드 |

### 🔲 4-10. Phase 9 — 샘플 데이터 + 통합 테스트

| 작업 | 설명 | 담당 |
|------|------|------|
| 샘플 파일 3종 | 세계관 + 설정집 + 시나리오 | 전체 |
| 검증용 원고 | 7유형 모순 포함 | 전체 |
| test_e2e.py | 5계층 전체 파이프라인 | 전체 |

---

## 5. 의사결정 기록

| # | 결정 사항 | 이유 |
|---|----------|------|
| 1 | **3분류 업로드: 세계관 / 설정집 / 시나리오** | 유형별 추출 전략이 다르고 GraphRAG 트랙 분리 필요 |
| 2 | **2트랙 GraphRAG** | 세계관·설정만으로도 사전 검증 가능 |
| 3 | **위키 기능 제거** | 설정집으로 대체 가능, 실서비스에서 미사용 |
| 4 | **이중 시간 축: discourse_order + story_order** | discourse_order(텍스트 순서) + story_order(서사 시점). 회상/비선형 서사를 예외 분기 없이 처리 |
| 5 | **7가지 모순 유형** | 정보비대칭 + 타임라인 + 관계 + 성격설정 + 감정 + 소유물 + 거짓말기만 |
| 6 | **의도성 판단은 사용자에게 위임** | 복선/의도적 변화는 작가만 판단 가능 |
| 7 | **사용자 확인에 반드시 원본 발췌** | 원본 없이 질문만 던지면 판단 불가 |
| 8 | **세계관 유무에 따라 확인 건수 변동** | 시나리오만→확인 증가(안전), 전부→확인 감소 |
| 9 | **LLM confidence≥0.8만 자동 판정** | 미만은 사용자 확인으로 전환 |
| 10 | **git commit+push 방식 수정 반영** | 여러 수정 모아서 한번에 반영 + 버전 관리 |
| 11 | **Push 시 원본 반영 + GraphRAG 재구축** | 수정 원고가 새 버전이 되고 그래프 갱신 |
| 12 | **다중 소스 충돌 시 사용자가 정본 결정** | 양쪽 원본 나란히 표시 |
| 13 | **과거 회상 감지 → 사용자 확인** | 서사 흐름 점프 시 자동 판단 않고 질문 |
| 14 | **사이드바+메인 레이아웃** | 프로젝트 목록 좌측, 선택 시 KB/소스/모순 즉시 표시 |
| 15 | **이벤트 소싱** | 시점별 상태 복원 가능 |
| 16 | **5계층 아키텍처** | Extraction → Normalization → Materialization → Detection → Review. 문제 발생 시 계층별 원인 식별 |
| 17 | **Normalization 계층 독립** | 동일 캐릭터 통합, 동일 사실 병합, 소스 충돌 감지를 별도 단계로 |
| 18 | **거짓말·기만 추적** | Fact.is_true + LEARNS.believed_true로 거짓 정보 전파 체인 추적 |
| 19 | **장면 환경 제약** | Event.environment로 환경-행동 불일치 탐지 |
| 20 | **세력/조직** | Organization + BELONGS_TO (가볍게, 조직 간 관계는 확장) |
| 21 | **목표/동기** | Trait.category 확장 (거의 전부 사용자 확인 영역) |
| 22 | **Fact vs Trait 구분** | "다른 캐릭터가 모를 수 있는가?" Yes→Fact, No→Trait, 비밀속성→양쪽 |
| 23 | **아이템 소유/접근 세분화** | POSSESSES.possession_type (owns/holds/can_access/guards) + Item.location_id |
| 24 | **[v2.2] 이중 시간 축** | discourse_order + story_order 분리로 회상/비선형 서사 처리. is_flashback 제거 |
| 25 | **[v2.2] Hard/Soft 형식 구분** | Hard=논리적 불가능(자동 판정), Soft=맥락에 따라 의도적(사용자 확인) |
| 26 | **[v2.2] 임시 그래프 격리** | analyze() 시 In-Memory 스냅샷 복제, canonical graph 보호, Push 시에만 업데이트 |

---

## 6. 새 세션 시작 시 체크리스트

1. **이 문서**(`conticheck-project-status.md`)를 첨부합니다.
2. 작업 대상에 따라 **관련 산출물을 함께 첨부**합니다:

| 작업할 내용 | 함께 첨부할 파일 |
|------------|----------------|
| 프론트엔드 작업 | `conticheck-v3.html` |
| 백엔드 구현 | `conticheck-claude-code-guide.md` + `conticheck-ontology-schema.md` |
| 온톨로지/DB 작업 | `conticheck-ontology-schema.md` + `conticheck-ontology-diagram.html` |
| LLM 프롬프트 작업 | `conticheck-claude-code-guide.md` + `conticheck-ontology-schema.md` |
| 전체 진행 확인 | 이 문서만으로 충분 |

3. 작업 완료 후 이 문서를 업데이트 요청합니다.

---

## 7. 다음 세션 우선 작업

1. **Phase 0 실행** — 프로젝트 스캐폴딩 + Pydantic 모델 (9노드+13엣지+중간 데이터 모델)
2. **Phase 1 실행** — 문서 파싱 + 추출 프롬프트 + ExtractionService
