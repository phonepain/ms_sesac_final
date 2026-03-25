"""LLM 비용 추적기.

파이프라인 시작 시 reset_tracker()를 호출하고,
각 LLM 응답 후 get_tracker().add(model, response.usage)를 호출하세요.
contextvars 기반이므로 asyncio 동시 요청 간 격리됩니다.
"""
import contextvars
from dataclasses import dataclass
from typing import Any

# ── 모델별 가격표 ($/1M 토큰) ──────────────────────────────────
# Azure OpenAI 배포 이름 → (입력 단가, 출력 단가)
# 실제 배포 모델이 바뀌면 이 딕셔너리만 수정하세요.
PRICING: dict[str, tuple[float, float]] = {
    "gpt-5.4-mini": (0.15, 0.60),
    "gpt-5.3-chat": (2.50, 10.00),
}
DEFAULT_PRICING: tuple[float, float] = (1.00, 3.00)  # 미등록 모델 폴백


@dataclass
class LLMUsageRecord:
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float


class LLMCostTracker:
    """단일 파이프라인 실행 동안의 LLM 사용량·비용을 누적합니다."""

    def __init__(self) -> None:
        self.records: list[LLMUsageRecord] = []

    def add(self, model: str, usage: Any) -> None:
        """LLM 응답의 usage 객체를 받아 토큰·비용을 기록합니다."""
        if usage is None:
            return
        pt = int(getattr(usage, "prompt_tokens", 0) or 0)
        ct = int(getattr(usage, "completion_tokens", 0) or 0)
        in_price, out_price = PRICING.get(model, DEFAULT_PRICING)
        cost = (pt * in_price + ct * out_price) / 1_000_000
        self.records.append(
            LLMUsageRecord(model=model, prompt_tokens=pt, completion_tokens=ct, cost_usd=cost)
        )

    def summary(self) -> dict:
        """집계 결과를 dict로 반환합니다 (AnalysisResponse.llm_cost 필드용)."""
        total_prompt = sum(r.prompt_tokens for r in self.records)
        total_completion = sum(r.completion_tokens for r in self.records)
        total_cost = sum(r.cost_usd for r in self.records)

        by_model: dict[str, dict] = {}
        for r in self.records:
            if r.model not in by_model:
                by_model[r.model] = {
                    "calls": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "cost_usd": 0.0,
                }
            by_model[r.model]["calls"] += 1
            by_model[r.model]["prompt_tokens"] += r.prompt_tokens
            by_model[r.model]["completion_tokens"] += r.completion_tokens
            by_model[r.model]["cost_usd"] += r.cost_usd

        return {
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "total_tokens": total_prompt + total_completion,
            "total_cost_usd": round(total_cost, 6),
            "calls": len(self.records),
            "by_model": {
                k: {**v, "cost_usd": round(v["cost_usd"], 6)}
                for k, v in by_model.items()
            },
        }


# ── ContextVar 기반 per-request 격리 ──────────────────────────

_current_tracker: contextvars.ContextVar[LLMCostTracker] = contextvars.ContextVar(
    "llm_cost_tracker"
)


def reset_tracker() -> LLMCostTracker:
    """파이프라인 시작 시 호출. 현재 asyncio 컨텍스트에 새 트래커를 설정합니다."""
    tracker = LLMCostTracker()
    _current_tracker.set(tracker)
    return tracker


def get_tracker() -> LLMCostTracker:
    """현재 컨텍스트의 트래커를 반환합니다. 없으면 새로 생성합니다."""
    try:
        return _current_tracker.get()
    except LookupError:
        return reset_tracker()
