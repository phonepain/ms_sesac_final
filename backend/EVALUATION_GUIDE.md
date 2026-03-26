# ContiCheck 평가 실행 가이드

## 1. 설치

```bash
cd backend
pip install -r requirements.txt
```

## 2. 환경 설정

```bash
cp .env.example .env
```

`.env` 파일에 Azure OpenAI API 키를 설정:

```
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
AZURE_OPENAI_API_KEY=your-api-key
```

## 3. 테스트 실행

### 전체 실행 (subprocess 개별, ~25분)

```bash
python scripts/run_all_tests.py
```

### 선택 실행

```bash
# 짧은 케이스만 (~3분)
python scripts/run_all_tests.py case500

# 중간 케이스 (~10분)
python scripts/run_all_tests.py case500 case1000 case1000v2 batch

# WSS 3파일 분리 케이스 (~15분)
python scripts/run_all_tests.py case2 cases3

# 긴 케이스 (~40분)
python scripts/run_all_tests.py long_case
```

### 개별 케이스 실행

```bash
# 스크립트 전체 실행
python scripts/case500_e2e_test.py

# 특정 케이스만 (0부터 시작)
python scripts/case500_e2e_test.py --case 0
```

## 4. 사용 가능한 테스트 스크립트

| 스크립트 | 대상 폴더 | 케이스 수 | 형식 | 예상 시간 |
|----------|----------|----------|------|----------|
| case500_e2e_test.py | claude_test_case500 | 4 | 단일파일 ~1KB | ~3분 |
| case1000_e2e_test.py | claude_test_case1000 | 4 | 단일파일 ~2KB | ~3분 |
| case1000v2_e2e_test.py | claude_test_case1000_v2 | 4 | 단일파일 ~1.7KB | ~3분 |
| case2000_e2e_test.py | claude_test_case2000 | 4 | 단일파일 3~4.5KB | ~4분 |
| batch_e2e_test.py | case | 4 | 단일파일 3~5KB | ~3분 |
| case2_e2e_test.py | cases2 | 8 | 3파일(W+S+S) | ~8분 |
| cases3_e2e_test.py | cases3 | 8 | 3파일(W+S+S) | ~10분 |
| long_case_e2e_test.py | case2plus | 4 | 3파일(긴 시나리오) | ~40분 |
| variation_e2e_test.py | cases | 5 | 3파일(W+S+S) | ~5분 |
| wss500_e2e_test.py | claude_test_wss500 | 4 | 단일(섹션분리) | ~3분 |
| wss1000_e2e_test.py | claude_test_wss1000 | 4 | 단일(섹션분리) | ~4분 |
| wss2_1000_e2e_test.py | claude_test_wss2_1000 | 4 | 3파일 분리 | ~4분 |

## 5. 결과 해석

### 출력 형식

```
[1/4] case500#0 ... case1 | 기대=3 탐지=2(-1) H=2 S=0 C=0 | 39s
```

- **기대**: expectation 파일 기준 모순 수
- **탐지**: 시스템이 찾은 모순 수
- **H**: Hard (자동 확정)
- **S**: Soft (자동 확정, confidence >= 0.8)
- **C**: Confirmation (사용자 확인 필요)

### 요약 테이블

```
그룹             케이스                        기대   탐지    차이     시간
────────────────────────────────────────────────────────────────
case500        case1                       3    2    -1    39s
...
합계                                        10    8    -2   163s
```

- 차이가 **음수**: 미탐지 (기대보다 적게 찾음)
- 차이가 **양수**: 과탐지 (기대보다 많이 찾음)
- 차이가 **0**: 이상적

## 6. 테스트 데이터 구조

### 단일 파일 (case500, case1000 등)

```
data/sample/claude_test_case500/
├── case1.txt           # 시나리오 텍스트
├── expectation1.txt    # 기대 모순 목록
├── case2.txt
├── expectation2.txt
...
```

### 3파일 분리 (cases2, cases3 등)

```
data/sample/cases2/
├── test_1_world.txt       # 세계관
├── test_1_config.txt      # 설정집
├── test_1_scenario.txt    # 시나리오
├── test_1_expectation.txt # 기대값 ("총 N건" 형식)
...
```

### 단일파일 섹션분리 (wss500, wss1000)

```
data/sample/claude_test_wss500/
├── case17.txt    # [세계관] [설정집] [시나리오] 섹션이 한 파일에 포함
├── expectation17.txt
...
```

## 7. 기준 성능 (Azure GPT-5.4-mini + GPT-5.3-chat, 2026-03-26)

| 테스트셋 | 기대 | 탐지 | 탐지율 |
|---------|------|------|--------|
| case500 | 10 | 10 | 100% |
| case1000 | 9 | 12 | 133% |
| case1000v2 | 21 | 17 | 81% |
| case2000 | 15 | 25 | 167% |
| batch | 23 | 18 | 78% |
| wss500 | 18 | 12 | 67% |
| cases2 | 38 | 38 | 100% |
| cases3 | 33 | 34 | 103% |
