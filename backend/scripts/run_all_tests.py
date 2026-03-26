"""전체 테스트를 subprocess로 케이스별 개별 실행 후 결과 수집.

각 스크립트의 각 케이스를 별도 프로세스로 실행하여:
- 상태 오염 없음 (그래프/서비스 격리)
- 하나 실패해도 나머지 진행
- 타임아웃 개별 관리

실행:
  python scripts/run_all_tests.py                    # 전체
  python scripts/run_all_tests.py long_case           # long_case만
  python scripts/run_all_tests.py case500 long_case   # 여러 스크립트
  python scripts/run_all_tests.py --save              # 결과를 results/ 에 JSON 저장
  python scripts/run_all_tests.py --save case500      # 특정만 실행 + 저장
"""
import subprocess
import sys
import os
import io
import json
import time
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(SCRIPTS_DIR)

# (표시명, 스크립트 파일명, 케이스 수)
ALL_TESTS = [
    ("case500",    "case500_e2e_test.py",    4),
    ("case1000",   "case1000_e2e_test.py",   4),
    ("case1000v2", "case1000v2_e2e_test.py",  4),
    ("case2000",   "case2000_e2e_test.py",   4),
    ("batch",      "batch_e2e_test.py",      4),
    ("case2",      "case2_e2e_test.py",      8),
    ("cases3",     "cases3_e2e_test.py",     8),
    ("long_case",  "long_case_e2e_test.py",  4),
    ("variation",  "variation_e2e_test.py",  5),
    ("wss500",     "wss500_e2e_test.py",    4),
    ("wss1000",    "wss1000_e2e_test.py",   4),
    ("wss2_1000",  "wss2_1000_e2e_test.py", 4),
]

CASE_TIMEOUT = 600  # 10분


def run_one_case(script: str, case_idx: int) -> dict:
    """단일 케이스를 subprocess로 실행, JSON 결과 파싱."""
    script_path = os.path.join(SCRIPTS_DIR, script)

    start = time.time()
    try:
        result = subprocess.run(
            [sys.executable, script_path, "--case", str(case_idx)],
            cwd=BACKEND_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CASE_TIMEOUT,
        )
        elapsed = time.time() - start
    except subprocess.TimeoutExpired:
        return {"error": f"타임아웃 ({CASE_TIMEOUT}s)", "elapsed": CASE_TIMEOUT}
    except Exception as e:
        return {"error": str(e), "elapsed": 0}

    # stdout에서 JSON 결과 라인 찾기 (마지막 유효 JSON 사용 — structlog도 {로 시작하므로)
    all_output = result.stdout + "\n" + result.stderr
    for line in reversed(all_output.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and '"name"' in line:
            try:
                data = json.loads(line)
                data["elapsed"] = round(elapsed, 1)
                return data
            except json.JSONDecodeError:
                pass

    # JSON 파싱 실패 시 stderr에서 에러 확인
    error_msg = ""
    for line in (result.stderr or "").splitlines():
        if "Error" in line or "error" in line:
            error_msg = line.strip()[:120]
            break

    return {
        "error": error_msg or f"JSON 파싱 실패 (exit={result.returncode})",
        "elapsed": round(elapsed, 1),
    }


RESULTS_DIR = os.path.join(BACKEND_DIR, "results")


def main():
    args = sys.argv[1:]
    save_mode = "--save" in args
    if save_mode:
        args.remove("--save")
    selected = args if args else None

    tests_to_run = []
    for name, script, count in ALL_TESTS:
        if selected and name not in selected:
            continue
        tests_to_run.append((name, script, count))

    if not tests_to_run:
        print(f"사용 가능한 테스트: {[n for n, _, _ in ALL_TESTS]}")
        return

    total_cases = sum(c for _, _, c in tests_to_run)
    print("=" * 74)
    print(f"  전체 E2E 테스트 — {len(tests_to_run)}개 스크립트, {total_cases}개 케이스 (subprocess 개별)")
    print("=" * 74)

    all_results = []  # [(group_name, case_name, result_dict), ...]
    grand_expected = 0
    grand_detected = 0
    grand_elapsed = 0
    case_num = 0

    for group_name, script, case_count in tests_to_run:
        print(f"\n{'─' * 74}")
        print(f"  [{group_name}] {script} ({case_count}개 케이스)")
        print(f"{'─' * 74}")

        group_expected = 0
        group_detected = 0
        group_elapsed = 0

        for i in range(case_count):
            case_num += 1
            sys.stdout.write(f"  [{case_num}/{total_cases}] {group_name}#{i} ... ")
            sys.stdout.flush()

            r = run_one_case(script, i)
            elapsed = r.get("elapsed", 0)
            group_elapsed += elapsed

            if r.get("error") and "total" not in r:
                print(f"ERROR ({elapsed:.0f}s) — {r['error']}")
                all_results.append((group_name, f"#{i}", r))
                continue

            exp = r.get("expected", 0)
            det = r.get("total", 0)
            hard = r.get("hard", 0)
            soft = r.get("soft", 0)
            conf = r.get("conf", 0)
            name = r.get("name", f"#{i}")
            group_expected += exp
            group_detected += det

            diff = det - exp
            diff_str = f"+{diff}" if diff > 0 else str(diff)
            print(f"{name} | 기대={exp} 탐지={det}({diff_str}) H={hard} S={soft} C={conf} | {elapsed:.0f}s")

            # 상세 출력
            for d in r.get("details", []):
                print(f"      {d}")

            all_results.append((group_name, name, r))

        grand_expected += group_expected
        grand_detected += group_detected
        grand_elapsed += group_elapsed

        diff = group_detected - group_expected
        diff_str = f"+{diff}" if diff > 0 else str(diff)
        print(f"  [{group_name} 소계] 기대={group_expected} 탐지={group_detected}({diff_str}) | {group_elapsed:.0f}s")

    # ── 전체 요약 ──
    print(f"\n{'=' * 74}")
    print("  전체 요약")
    print(f"{'=' * 74}")
    print(f"  {'그룹':<14} {'케이스':<24} {'기대':>4} {'탐지':>4} {'차이':>5} {'시간':>6}")
    print(f"  {'─' * 64}")

    for group_name, case_name, r in all_results:
        if r.get("error") and "total" not in r:
            print(f"  {group_name:<14} {case_name:<24} {'ERR':>4}")
            continue
        exp = r.get("expected", 0)
        det = r.get("total", 0)
        diff = det - exp
        diff_str = f"+{diff}" if diff > 0 else str(diff)
        elapsed = r.get("elapsed", 0)
        print(f"  {group_name:<14} {case_name:<24} {exp:>4} {det:>4} {diff_str:>5} {elapsed:>5.0f}s")

    print(f"  {'─' * 64}")
    diff_total = grand_detected - grand_expected
    diff_str = f"+{diff_total}" if diff_total > 0 else str(diff_total)
    print(f"  {'합계':<14} {'':<24} {grand_expected:>4} {grand_detected:>4} {diff_str:>5} {grand_elapsed:>5.0f}s")
    print(f"{'=' * 74}")

    # ── 결과 저장 ──
    if save_mode:
        os.makedirs(RESULTS_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        for group_name, case_name, r in all_results:
            safe_name = f"{group_name}_{case_name}".replace("#", "").replace(" ", "_")
            outpath = os.path.join(RESULTS_DIR, f"{safe_name}.json")
            r["_group"] = group_name
            r["_timestamp"] = timestamp
            with open(outpath, "w", encoding="utf-8") as f:
                json.dump(r, f, ensure_ascii=False, indent=2)

        print(f"\n  결과 저장: {RESULTS_DIR}/ ({len(all_results)}개 파일)")
        print(f"  통합 평가: python -m evaluation.evaluate_results")


if __name__ == "__main__":
    main()
