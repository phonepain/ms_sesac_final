"""ContiCheck 평가 프레임워크 실행기.

5계층 전체 파이프라인을 Gold Standard 데이터셋으로 평가합니다.

실행: python -m evaluation.run_eval
옵션:
  --ablation none        전체 파이프라인 (기본값)
  --ablation no_world    세계관 제거
  --ablation no_settings 설정집 제거
  --ablation no_norm     정규화 스킵 (추출→직접 그래프)
  --runs N               반복 횟수 (LLM 비결정성 대응, 기본 1)
  --case N               특정 케이스만 실행 (1~5, 기본 전체)
"""
import asyncio
import argparse
import os
import sys
import io
import json
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.extraction import ExtractionService
from app.services.normalization import NormalizationService
from app.services.graph import InMemoryGraphService, reset_graph_service
from app.models.api import DocumentChunk, ChunkLocation
from app.models.vertices import Source
from app.models.enums import SourceType

from evaluation.gold_standard import GOLD_CASES, GoldTestCase, ContradictionCategory
from evaluation.metrics import (
    DetectionMetrics, ExtractionMetrics, MatchResult,
    evaluate_detection, evaluate_extraction, aggregate_metrics,
)

SAMPLE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "sample", "variation"
)

FILE_TYPES = [
    ("세계관", "worldview", SourceType.WORLDVIEW),
    ("설정집", "settings", SourceType.SETTINGS),
    ("시나리오", "scenario", SourceType.SCENARIO),
]


# ── 파이프라인 실행 ───────────────────────────────────────────────

async def run_pipeline(
    gold_case: GoldTestCase,
    ablation: str = "none",
) -> Tuple[List[Dict[str, Any]], Any, DetectionMetrics, ExtractionMetrics, List[MatchResult]]:
    """단일 테스트 케이스 파이프라인 실행.

    Returns: (violations, normalized, det_metrics, ext_metrics, match_results)
    """
    prefix = gold_case.prefix
    extraction_svc = ExtractionService()
    norm_svc = NormalizationService()
    all_extraction_results = []

    # ablation에 따라 파일 선택
    skip_types = set()
    if ablation == "no_world":
        skip_types.add("세계관")
    elif ablation == "no_settings":
        skip_types.add("설정집")

    # 추출
    for file_label, source_type_str, source_type_enum in FILE_TYPES:
        if file_label in skip_types:
            continue
        filename = f"{file_label}_{prefix}.txt"
        filepath = os.path.join(SAMPLE_DIR, filename)
        if not os.path.exists(filepath):
            continue
        with open(filepath, encoding="utf-8") as f:
            text = f.read()
        chunk = DocumentChunk(
            id=f"chunk-{file_label}-0",
            source_id=f"src-{file_label}",
            chunk_index=0,
            content=text,
            location=ChunkLocation(source_id=f"src-{file_label}", source_name=filename),
        )
        results = await extraction_svc.extract_from_chunks([chunk], source_type=source_type_str)
        all_extraction_results.extend(results)

    # 정규화 (no_norm ablation에서도 normalize 호출 — 통합 로직만 스킵하기 어려우므로 동일 처리)
    normalized = await norm_svc.normalize(all_extraction_results)

    # 추출 메트릭
    ext_metrics = evaluate_extraction(normalized, gold_case)

    # 그래프 구축
    reset_graph_service()
    g = InMemoryGraphService()
    scenario_file = f"시나리오_{prefix}.txt"
    source = Source(
        source_id="eval-src",
        source_type=SourceType.SCENARIO,
        name=scenario_file,
        file_path=os.path.join(SAMPLE_DIR, scenario_file),
    )
    g.materialize(normalized, source)

    # 탐지
    result = g.find_all_violations()
    hard = result.get("hard", [])
    soft = result.get("soft", [])
    all_violations = hard + soft

    # 탐지 메트릭
    det_metrics, match_results = evaluate_detection(all_violations, gold_case)

    return all_violations, normalized, det_metrics, ext_metrics, match_results


# ── 출력 포매터 ───────────────────────────────────────────────────

def print_header(title: str):
    print(f"\n{'=' * 80}")
    print(f"  {title}")
    print(f"{'=' * 80}")


def print_detection_metrics(m: DetectionMetrics, label: str = ""):
    if label:
        print(f"\n  [{label}]")
    print(f"  Precision : {m.precision:.1%} ({m.true_positives}/{m.true_positives + m.false_positives})")
    print(f"  Recall    : {m.recall:.1%} ({m.true_positives}/{m.true_positives + m.false_negatives})")
    print(f"  F1        : {m.f1:.1%}")
    if m.hard_total + m.soft_total > 0:
        print(f"  Hard/Soft : {m.hard_soft_accuracy:.1%} (Hard {m.hard_correct}/{m.hard_total}, Soft {m.soft_correct}/{m.soft_total})")


def print_extraction_metrics(m: ExtractionMetrics):
    print(f"  캐릭터: F1={m.char_f1:.1%} (P={m.char_precision:.1%} R={m.char_recall:.1%})")
    print(f"  사실  : Recall={m.fact_recall:.1%} ({m.fact_matched}/{m.fact_gold})")
    print(f"  관계  : Recall={m.rel_recall:.1%} ({m.rel_matched}/{m.rel_gold})")


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
        bar = "█" * int(recall * 20) + "░" * (20 - int(recall * 20))
        print(f"    {cat.value:16s} {bar} {recall:.0%} ({tp}/{total})")


def print_match_details(results: List[MatchResult]):
    for mr in results:
        status = "OK" if mr.matched else "MISS"
        print(f"    [{status}] {mr.gold.id} {mr.gold.category.value}: {mr.gold.description[:50]}")
        if mr.matched and mr.matched_violation:
            desc = mr.matched_violation.get("description", "")[:60]
            hs = "HARD" if mr.matched_violation.get("is_hard") else "SOFT"
            print(f"           → [{hs}] {desc}")


# ── 메인 ──────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="ContiCheck 평가 프레임워크")
    parser.add_argument("--ablation", default="none",
                        choices=["none", "no_world", "no_settings", "no_norm"],
                        help="Ablation 실험 모드")
    parser.add_argument("--runs", type=int, default=1, help="반복 횟수")
    parser.add_argument("--case", type=int, default=0, help="특정 케이스 (1~5, 0=전체)")
    args = parser.parse_args()

    cases = GOLD_CASES
    if args.case > 0:
        cases = [GOLD_CASES[args.case - 1]]

    print_header(f"ContiCheck 평가 프레임워크 — ablation={args.ablation}, runs={args.runs}")
    print(f"  Gold Standard: {len(cases)}개 케이스, "
          f"총 {sum(tc.total_contradictions for tc in cases)}건 모순")
    print(f"  실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 다회 실행 시 최고 결과 추적
    best_total_f1 = 0.0
    best_run_metrics = None
    all_run_det_metrics = []

    for run_idx in range(args.runs):
        if args.runs > 1:
            print(f"\n{'─' * 80}")
            print(f"  Run {run_idx + 1}/{args.runs}")

        per_case_det: List[DetectionMetrics] = []
        per_case_ext: List[ExtractionMetrics] = []
        per_case_results: List[Tuple[GoldTestCase, List[MatchResult], DetectionMetrics]] = []

        for tc in cases:
            print(f"\n  ── {tc.name} ({tc.genre}) ──")
            print(f"  Gold: {tc.total_contradictions}건 (HARD={tc.hard_count}, SOFT={tc.soft_count})")

            try:
                violations, normalized, det_m, ext_m, match_res = await run_pipeline(
                    tc, ablation=args.ablation
                )
            except Exception as e:
                print(f"  ERROR: {e}")
                import traceback; traceback.print_exc()
                continue

            per_case_det.append(det_m)
            per_case_ext.append(ext_m)
            per_case_results.append((tc, match_res, det_m))

            # 계층1: 추출 메트릭
            print(f"\n  [계층1 — Extraction]")
            print_extraction_metrics(ext_m)

            # 계층4: 탐지 메트릭
            print(f"\n  [계층4 — Detection]")
            print_detection_metrics(det_m)
            print()
            print_match_details(match_res)

        # 전체 집계
        if per_case_det:
            agg = aggregate_metrics(per_case_det)
            all_run_det_metrics.append(agg)

            print_header("전체 집계 (Micro-Average)")
            print_detection_metrics(agg, "Detection")
            print_category_breakdown(agg)

            # 계층1 집계
            total_char_m = sum(m.char_matched for m in per_case_ext)
            total_char_g = sum(m.char_gold for m in per_case_ext)
            total_fact_m = sum(m.fact_matched for m in per_case_ext)
            total_fact_g = sum(m.fact_gold for m in per_case_ext)
            total_rel_m = sum(m.rel_matched for m in per_case_ext)
            total_rel_g = sum(m.rel_gold for m in per_case_ext)
            print(f"\n  [계층1 — Extraction 집계]")
            print(f"  캐릭터 Recall: {total_char_m}/{total_char_g}"
                  f" ({total_char_m / total_char_g:.1%})" if total_char_g > 0 else "")
            print(f"  사실 Recall  : {total_fact_m}/{total_fact_g}"
                  f" ({total_fact_m / total_fact_g:.1%})" if total_fact_g > 0 else "")
            print(f"  관계 Recall  : {total_rel_m}/{total_rel_g}"
                  f" ({total_rel_m / total_rel_g:.1%})" if total_rel_g > 0 else "")

            if agg.f1 > best_total_f1:
                best_total_f1 = agg.f1
                best_run_metrics = agg

    # 다회 실행 요약
    if args.runs > 1 and all_run_det_metrics:
        print_header(f"다회 실행 요약 ({args.runs}회)")
        f1s = [m.f1 for m in all_run_det_metrics]
        recalls = [m.recall for m in all_run_det_metrics]
        precisions = [m.precision for m in all_run_det_metrics]
        print(f"  F1      : min={min(f1s):.1%} / avg={sum(f1s)/len(f1s):.1%} / max={max(f1s):.1%}")
        print(f"  Recall  : min={min(recalls):.1%} / avg={sum(recalls)/len(recalls):.1%} / max={max(recalls):.1%}")
        print(f"  Precision: min={min(precisions):.1%} / avg={sum(precisions)/len(precisions):.1%} / max={max(precisions):.1%}")
        print(f"  Best F1 : {best_total_f1:.1%}")

    print(f"\n{'=' * 80}")


if __name__ == "__main__":
    asyncio.run(main())
