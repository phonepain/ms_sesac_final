"""평가 메트릭 계산 모듈.

계층별 Precision / Recall / F1 + 유형별 세분화.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from evaluation.gold_standard import (
    GoldTestCase, GoldContradiction, ContradictionCategory, HardSoft,
)


@dataclass
class MatchResult:
    """Gold 모순 1건의 매칭 결과"""
    gold: GoldContradiction
    matched: bool = False
    matched_violation: Optional[Dict[str, Any]] = None
    match_score: float = 0.0  # 0~1, 키워드 매칭 비율


@dataclass
class DetectionMetrics:
    """계층4 탐지 메트릭"""
    # 기본 수치
    true_positives: int = 0   # Gold에 있고 탐지함
    false_positives: int = 0  # Gold에 없는데 탐지함
    false_negatives: int = 0  # Gold에 있는데 탐지 못함

    # 유형별 TP/FN
    tp_by_category: Dict[ContradictionCategory, int] = field(default_factory=dict)
    fn_by_category: Dict[ContradictionCategory, int] = field(default_factory=dict)

    # Hard/Soft 정확도
    hard_correct: int = 0
    hard_total: int = 0
    soft_correct: int = 0
    soft_total: int = 0

    @property
    def precision(self) -> float:
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom > 0 else 0.0

    @property
    def recall(self) -> float:
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom > 0 else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0

    @property
    def hard_soft_accuracy(self) -> float:
        total = self.hard_total + self.soft_total
        correct = self.hard_correct + self.soft_correct
        return correct / total if total > 0 else 0.0

    def category_f1(self, cat: ContradictionCategory) -> float:
        tp = self.tp_by_category.get(cat, 0)
        fn = self.fn_by_category.get(cat, 0)
        # FP는 카테고리별로 세분화하기 어려우므로 Recall만 사용
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        return recall  # category-level recall (precision은 전체 기준)


@dataclass
class ExtractionMetrics:
    """계층1 추출 메트릭"""
    # 캐릭터
    char_extracted: int = 0
    char_gold: int = 0
    char_matched: int = 0

    # 사실/규칙
    fact_extracted: int = 0
    fact_gold: int = 0
    fact_matched: int = 0

    # 관계
    rel_extracted: int = 0
    rel_gold: int = 0
    rel_matched: int = 0

    @property
    def char_precision(self) -> float:
        return self.char_matched / self.char_extracted if self.char_extracted > 0 else 0.0

    @property
    def char_recall(self) -> float:
        return self.char_matched / self.char_gold if self.char_gold > 0 else 0.0

    @property
    def char_f1(self) -> float:
        p, r = self.char_precision, self.char_recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0

    @property
    def fact_recall(self) -> float:
        return self.fact_matched / self.fact_gold if self.fact_gold > 0 else 0.0

    @property
    def rel_recall(self) -> float:
        return self.rel_matched / self.rel_gold if self.rel_gold > 0 else 0.0


# ── 매칭 함수 ─────────────────────────────────────────────────────

def match_violation_to_gold(
    violation: Dict[str, Any],
    gold: GoldContradiction,
    threshold: float = 0.3,
) -> Tuple[bool, float]:
    """시스템이 탐지한 violation이 gold 모순과 매칭되는지 판정.

    Returns: (matched, score)
    """
    desc = violation.get("description", "")
    evidence_str = str(violation.get("evidence", ""))
    combined = desc + " " + evidence_str

    if not gold.keywords:
        return False, 0.0

    hit = sum(1 for kw in gold.keywords if kw in combined)
    score = hit / len(gold.keywords)
    return score >= threshold, score


def evaluate_detection(
    violations: List[Dict[str, Any]],
    gold_case: GoldTestCase,
    match_threshold: float = 0.3,
) -> Tuple[DetectionMetrics, List[MatchResult]]:
    """탐지 결과를 gold standard와 비교하여 메트릭 계산.

    Args:
        violations: find_all_violations() 결과의 hard+soft 합산 리스트
        gold_case: 해당 테스트 케이스의 gold standard
        match_threshold: 키워드 매칭 임계값

    Returns:
        (DetectionMetrics, per-contradiction MatchResult list)
    """
    metrics = DetectionMetrics()
    results: List[MatchResult] = []
    used_violations: set = set()

    # Gold 모순별로 매칭 시도
    for gc in gold_case.contradictions:
        mr = MatchResult(gold=gc)
        best_score = 0.0
        best_idx = -1

        for idx, v in enumerate(violations):
            if idx in used_violations:
                continue
            matched, score = match_violation_to_gold(v, gc, match_threshold)
            if matched and score > best_score:
                best_score = score
                best_idx = idx

        if best_idx >= 0:
            mr.matched = True
            mr.matched_violation = violations[best_idx]
            mr.match_score = best_score
            used_violations.add(best_idx)
            metrics.true_positives += 1
            metrics.tp_by_category[gc.category] = metrics.tp_by_category.get(gc.category, 0) + 1

            # Hard/Soft 정확도
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
            metrics.fn_by_category[gc.category] = metrics.fn_by_category.get(gc.category, 0) + 1

        results.append(mr)

    # 매칭 안 된 탐지 = False Positive
    metrics.false_positives = len(violations) - len(used_violations)

    return metrics, results


def evaluate_extraction(
    normalized,  # NormalizationResult
    gold_case: GoldTestCase,
) -> ExtractionMetrics:
    """추출+정규화 결과를 gold standard와 비교.

    Args:
        normalized: NormalizationService.normalize() 결과
        gold_case: 해당 테스트 케이스의 gold standard
    """
    metrics = ExtractionMetrics()

    # 캐릭터 매칭
    extracted_names = set()
    for nc in normalized.characters:
        extracted_names.add(nc.canonical_name)
        extracted_names.update(nc.all_aliases)
    metrics.char_extracted = len(normalized.characters)
    metrics.char_gold = len(gold_case.characters)
    for gc in gold_case.characters:
        all_names = {gc.canonical_name} | set(gc.aliases)
        if any(n in extracted_names for n in all_names):
            metrics.char_matched += 1

    # Fact 매칭 (부분 문자열 매칭)
    extracted_facts = [nf.content for nf in normalized.facts]
    metrics.fact_extracted = len(extracted_facts)
    metrics.fact_gold = len(gold_case.facts)
    for gf in gold_case.facts:
        # gold fact의 핵심 키워드가 추출된 fact 중 하나에 포함되면 매칭
        gf_words = [w for w in gf.content.split() if len(w) >= 2][:5]
        for ef in extracted_facts:
            if sum(1 for w in gf_words if w in ef) >= max(1, len(gf_words) // 2):
                metrics.fact_matched += 1
                break

    # 관계 매칭
    extracted_rels = []
    for nr in normalized.relationships:
        extracted_rels.append((nr.char_a, nr.char_b, nr.type_hint or ""))
    metrics.rel_extracted = len(extracted_rels)
    metrics.rel_gold = len(gold_case.relationships)
    for gr in gold_case.relationships:
        for ea, eb, etype in extracted_rels:
            if (gr.char_a in ea or ea in gr.char_a) and (gr.char_b in eb or eb in gr.char_b):
                metrics.rel_matched += 1
                break

    return metrics


# ── 집계 함수 ─────────────────────────────────────────────────────

def aggregate_metrics(per_case: List[DetectionMetrics]) -> DetectionMetrics:
    """여러 테스트 케이스의 메트릭을 합산 (micro-average)."""
    agg = DetectionMetrics()
    for m in per_case:
        agg.true_positives += m.true_positives
        agg.false_positives += m.false_positives
        agg.false_negatives += m.false_negatives
        agg.hard_correct += m.hard_correct
        agg.hard_total += m.hard_total
        agg.soft_correct += m.soft_correct
        agg.soft_total += m.soft_total
        for cat, val in m.tp_by_category.items():
            agg.tp_by_category[cat] = agg.tp_by_category.get(cat, 0) + val
        for cat, val in m.fn_by_category.items():
            agg.fn_by_category[cat] = agg.fn_by_category.get(cat, 0) + val
    return agg
