"""저장된 테스트 결과 JSON으로 Gold Standard 대비 통합 평가.

AI/LLM 호출 없이 로컬에서 실행 가능.

사용법:
  # 1단계: 테스트 실행 + 결과 저장 (AI 필요)
  python scripts/run_all_tests.py --save
  python scripts/run_all_tests.py --save case500 case1000v2

  # 2단계: 통합 평가 (AI 불필요)
  python -m evaluation.evaluate_results                    # results/ 전체
  python -m evaluation.evaluate_results --dir results/     # 경로 지정
  python -m evaluation.evaluate_results --set case500      # 특정 셋만
"""
import os
import sys
import io
import json
import argparse
from typing import List, Dict, Any, Tuple
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evaluation.gold_standard import (
    load_gold_from_json, get_gold_by_name, GoldTestCase, GoldContradiction,
    ContradictionCategory, HardSoft,
)
from evaluation.metrics import (
    DetectionMetrics, MatchResult, aggregate_metrics,
    match_violation_to_gold,
)


# ── 결과 로드 ──────────────────────────────────────────────────

def load_results(results_dir: str) -> List[Dict[str, Any]]:
    """results/ 디렉토리에서 모든 JSON 결과 로드."""
    results = []
    if not os.path.isdir(results_dir):
        print(f"  ERROR: {results_dir} 디렉토리 없음")
        return results

    for filename in sorted(os.listdir(results_dir)):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(results_dir, filename)
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)
        data["_filename"] = filename
        results.append(data)

    return results


def result_to_violations(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """테스트 결과 JSON에서 violations 리스트로 변환.

    details가 문자열 리스트 또는 dict 리스트 모두 처리.
    """
    violations = []
    for detail in result.get("details", []):
        if isinstance(detail, dict):
            # dict 형태: {kind, confidence, type, description/desc}
            kind = detail.get("kind", "")
            desc = detail.get("description", "") or detail.get("desc", "")
            is_hard = kind.upper() == "HARD" or detail.get("severity", "") == "critical"
            is_conf = kind.upper() == "CONF"
            raw = f"[{kind.upper()}] ({detail.get('confidence', '')}) {detail.get('type', '')}: {desc}"
            violations.append({
                "description": desc,
                "is_hard": is_hard,
                "is_confirmation": is_conf,
                "raw": raw,
            })
        else:
            # 문자열 형태: "[HARD] (0.98) timeline: 설명..."
            is_hard = "[HARD]" in detail
            is_conf = "[CONF]" in detail
            desc = detail
            parts = detail.split(": ", 1)
            if len(parts) > 1:
                desc = parts[1]
            violations.append({
                "description": desc,
                "is_hard": is_hard,
                "is_confirmation": is_conf,
                "raw": detail,
            })
    return violations


# ── 매칭 ──────────────────────────────────────────────────────

def evaluate_single(
    result: Dict[str, Any],
    gold: GoldTestCase,
    threshold: float = 0.3,
) -> Tuple[DetectionMetrics, List[MatchResult]]:
    """단일 케이스 결과를 Gold Standard와 비교."""
    violations = result_to_violations(result)
    metrics = DetectionMetrics()
    match_results: List[MatchResult] = []
    used: set = set()

    for gc in gold.contradictions:
        mr = MatchResult(gold=gc)
        best_score = 0.0
        best_idx = -1

        for idx, v in enumerate(violations):
            if idx in used:
                continue
            matched, score = match_violation_to_gold(v, gc, threshold)
            if matched and score > best_score:
                best_score = score
                best_idx = idx

        if best_idx >= 0:
            mr.matched = True
            mr.matched_violation = violations[best_idx]
            mr.match_score = best_score
            used.add(best_idx)
            metrics.true_positives += 1
            metrics.tp_by_category[gc.category] = \
                metrics.tp_by_category.get(gc.category, 0) + 1

            sys_hard = violations[best_idx].get("is_hard", False)
            if gc.hard_soft == HardSoft.HARD:
                metrics.hard_total += 1
                if sys_hard:
                    metrics.hard_correct += 1
            else:
                metrics.soft_total += 1
                if not sys_hard:
                    metrics.soft_correct += 1
        else:
            metrics.false_negatives += 1
            metrics.fn_by_category[gc.category] = \
                metrics.fn_by_category.get(gc.category, 0) + 1

        match_results.append(mr)

    metrics.false_positives = len(violations) - len(used)
    return metrics, match_results


# ── 출력 ──────────────────────────────────────────────────────

def print_metrics(m: DetectionMetrics, label: str = ""):
    if label:
        print(f"\n  [{label}]")
    tp, fp, fn = m.true_positives, m.false_positives, m.false_negatives
    print(f"  Precision : {m.precision:.1%} ({tp}/{tp + fp})")
    print(f"  Recall    : {m.recall:.1%} ({tp}/{tp + fn})")
    print(f"  F1        : {m.f1:.1%}")
    if m.hard_total + m.soft_total > 0:
        print(f"  Hard/Soft : {m.hard_soft_accuracy:.1%} "
              f"(Hard {m.hard_correct}/{m.hard_total}, "
              f"Soft {m.soft_correct}/{m.soft_total})")


def print_category_breakdown(m: DetectionMetrics):
    print(f"\n  유형별 Recall:")
    all_cats = set(list(m.tp_by_category.keys()) + list(m.fn_by_category.keys()))
    for cat in ContradictionCategory:
        if cat not in all_cats:
            continue
        tp = m.tp_by_category.get(cat, 0)
        fn = m.fn_by_category.get(cat, 0)
        total = tp + fn
        recall = tp / total if total > 0 else 0.0
        bar = "#" * int(recall * 20) + "." * (20 - int(recall * 20))
        print(f"    {cat.value:20s} {bar} {recall:.0%} ({tp}/{total})")


# ── 이름 매핑 (테스트 스크립트 name → Gold Standard name) ─────

_NAME_MAP = {
    # batch_e2e_test.py → gold "batch_N"
    "테스트 01: 화성 연구 기지": "batch_1",
    "테스트 02: 마법 왕국": "batch_2",
    "테스트 03: 심해 잠수정": "batch_3",
    "테스트 04: 시간 연구소": "batch_4",
    # case2_e2e_test.py → gold "cases2_N"
    "test_1: 심해 관측기지 아비스-9": "cases2_1",
    "test_2: 공중도시 루멘 아크": "cases2_2",
    "test_3: 중앙지방법원 12호 법정": "cases2_3",
    "test_4: 사막왕국 아샤르": "cases2_4",
    "test_5: e스포츠 아레나 제로돔": "cases2_5",
    "test_6: 수도원 은종회랑": "cases2_6",
    "test_7: 궤도 교도소 헬릭스 (시나리오 단독)": "cases2_7",
    "test_8: 격리 병원 화이트돔 (시나리오 단독)": "cases2_8",
    # cases3_e2e_test.py → gold "cases3_*"
    "test_c500_13": "cases3_c500_13",
    "test_c500_14": "cases3_c500_14",
    "test_c500_15": "cases3_c500_15",
    "test_c500_16": "cases3_c500_16",
    "test_c1000_17": "cases3_c1000_17",
    "test_c1000_18": "cases3_c1000_18",
    "test_c1000_19": "cases3_c1000_19",
    "test_c1000_20": "cases3_c1000_20",
    # long_case_e2e_test.py → gold "long_N"
    "test_9: 연구소 야간 사건": "long_9",
    "test_10": "long_10",
    "test_11": "long_11",
    "test_12": "long_12",
}


def _resolve_gold_name(case_name: str) -> str:
    """테스트 결과의 case_name을 Gold Standard name으로 변환."""
    return _NAME_MAP.get(case_name, case_name)


# ── 메인 ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ContiCheck 통합 평가 (AI 불필요)")
    parser.add_argument("--dir", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results"
    ), help="결과 JSON 디렉토리 (기본: backend/results/)")
    parser.add_argument("--set", nargs="*", default=None,
                        help="특정 테스트 셋만 평가 (예: case500 case1000v2)")
    parser.add_argument("--threshold", type=float, default=0.3,
                        help="키워드 매칭 임계값 (기본: 0.3)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="매칭 상세 출력")
    args = parser.parse_args()

    # Gold Standard 로드
    gold_cases = load_gold_from_json()
    gold_by_name = {gc.name: gc for gc in gold_cases}

    # 결과 로드
    results = load_results(args.dir)
    if not results:
        print("결과 파일 없음. 먼저 테스트를 실행하세요:")
        print("  python scripts/run_all_tests.py --save")
        return

    # 셋 필터
    if args.set:
        results = [r for r in results if r.get("_group", "") in args.set]

    print("=" * 74)
    print(f"  ContiCheck 통합 평가")
    print(f"  결과: {len(results)}개 | Gold: {len(gold_cases)}개 | threshold: {args.threshold}")
    print(f"  시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 74)

    per_case_metrics: List[DetectionMetrics] = []
    per_set_metrics: Dict[str, List[DetectionMetrics]] = {}
    matched_count = 0
    unmatched_results = []

    for r in results:
        case_name = r.get("name", "")
        group = r.get("_group", "unknown")

        if r.get("error") and "total" not in r:
            print(f"  SKIP: {group}/{case_name} (에러: {r['error'][:50]})")
            continue

        # Gold 매칭 (이름 매핑 적용)
        gold_name = _resolve_gold_name(case_name)
        gold = gold_by_name.get(gold_name)
        if not gold:
            unmatched_results.append((group, case_name, r))
            continue

        matched_count += 1
        metrics, match_results = evaluate_single(r, gold, args.threshold)
        per_case_metrics.append(metrics)
        per_set_metrics.setdefault(group, []).append(metrics)

        if args.verbose:
            print(f"\n  -- {group}/{case_name} --")
            print(f"     Gold: {gold.total_contradictions}건 | "
                  f"탐지: {r.get('total', 0)}건 | "
                  f"TP={metrics.true_positives} FP={metrics.false_positives} "
                  f"FN={metrics.false_negatives}")
            for mr in match_results:
                status = "OK  " if mr.matched else "MISS"
                print(f"     [{status}] {mr.gold.description[:60]}")
                if mr.matched and mr.matched_violation:
                    print(f"            -> {mr.matched_violation.get('raw', '')[:60]}")

    # ── 셋별 집계 ──
    print(f"\n{'─' * 74}")
    print(f"  셋별 메트릭")
    print(f"{'─' * 74}")
    print(f"  {'셋':<14} {'케이스':>4} {'TP':>4} {'FP':>4} {'FN':>4} "
          f"{'P':>7} {'R':>7} {'F1':>7}")
    print(f"  {'─' * 60}")

    for set_name in sorted(per_set_metrics.keys()):
        agg = aggregate_metrics(per_set_metrics[set_name])
        n_cases = len(per_set_metrics[set_name])
        print(f"  {set_name:<14} {n_cases:>4} {agg.true_positives:>4} "
              f"{agg.false_positives:>4} {agg.false_negatives:>4} "
              f"{agg.precision:>6.1%} {agg.recall:>6.1%} {agg.f1:>6.1%}")

    # ── 전체 집계 ──
    if per_case_metrics:
        total = aggregate_metrics(per_case_metrics)
        print(f"  {'─' * 60}")
        print(f"  {'전체':<14} {matched_count:>4} {total.true_positives:>4} "
              f"{total.false_positives:>4} {total.false_negatives:>4} "
              f"{total.precision:>6.1%} {total.recall:>6.1%} {total.f1:>6.1%}")

        print_metrics(total, "전체 Detection 메트릭")
        print_category_breakdown(total)

    # Gold 미매칭 결과
    if unmatched_results:
        print(f"\n  Gold Standard 미매칭: {len(unmatched_results)}건")
        print(f"  (Gold에 해당 case_name이 없음 — generate_gold.py 재실행 필요)")
        for g, n, r in unmatched_results[:5]:
            print(f"    {g}/{n}: 탐지={r.get('total', '?')} 기대={r.get('expected', '?')}")

    print(f"\n{'=' * 74}")


if __name__ == "__main__":
    main()
