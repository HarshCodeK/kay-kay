from dataclasses import dataclass
from math import isfinite
from threading import Lock
from typing import Callable


@dataclass(frozen=True, slots=True)
class Request:
    api_key: str
    model: str
    prompt: str
    max_tokens: int = 256


@dataclass(frozen=True, slots=True)
class Response:
    text: str
    provider: str
    estimated_cost: float


class Gateway:
    """Single-process gateway policy with bounded usage telemetry."""

    MAX_PROMPT_CHARS = 20_000
    MAX_COMPLETION_TOKENS = 4_096
    MAX_USAGE_RECORDS = 2_048

    def __init__(self, providers: dict[str, Callable], prices: dict[str, float], budget: float = 1.0):
        if not isfinite(budget) or budget < 0:
            raise ValueError("budget must be finite and non-negative")
        if not providers:
            raise ValueError("at least one provider is required")
        if not prices or any(not isfinite(price) or price < 0 for price in prices.values()):
            raise ValueError("model prices must be finite and non-negative")
        self.providers = dict(providers)
        self.prices = dict(prices)
        self.budget = budget
        self.spent = 0.0
        self.reserved = 0.0
        self.usage: list[dict] = []
        self._lock = Lock()

    def estimate(self, request: Request) -> float:
        if request.model not in self.prices:
            raise RuntimeError("unknown_model")
        if not isinstance(request.prompt, str) or not request.prompt.strip() or len(request.prompt) > self.MAX_PROMPT_CHARS:
            raise RuntimeError("invalid_prompt")
        if not isinstance(request.max_tokens, int) or isinstance(request.max_tokens, bool) or not 1 <= request.max_tokens <= self.MAX_COMPLETION_TOKENS:
            raise RuntimeError("invalid_max_tokens")
        # Deliberately a rough token/cost estimate for the stub gateway, not billing.
        estimated_tokens = max(1, len(request.prompt.split()) + request.max_tokens)
        return estimated_tokens / 1000 * self.prices[request.model]

    def complete(self, request: Request) -> Response:
        reservation = self.estimate(request)
        with self._lock:
            if self.spent + self.reserved + reservation > self.budget:
                raise RuntimeError("budget_exceeded")
            self.reserved += reservation

        committed = False
        try:
            failures = []
            for name, call in self.providers.items():
                try:
                    text = call(request)
                    if not isinstance(text, str):
                        raise RuntimeError("provider_returned_non_text")
                    with self._lock:
                        self.reserved -= reservation
                        self.spent += reservation
                        self.usage.append({"provider": name, "model": request.model, "cost": reservation})
                        if len(self.usage) > self.MAX_USAGE_RECORDS:
                            del self.usage[:len(self.usage) - self.MAX_USAGE_RECORDS]
                    committed = True
                    return Response(text, name, reservation)
                except Exception:
                    failures.append(name)
            raise RuntimeError("all_providers_failed: " + ", ".join(failures))
        finally:
            if not committed:
                with self._lock:
                    self.reserved = max(0.0, self.reserved - reservation)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "scope": "this_process_only",
                "budget": self.budget,
                "spent_estimate": round(self.spent, 8),
                "reserved_estimate": round(self.reserved, 8),
                "usage_records_retained": len(self.usage),
                "usage_records_limit": self.MAX_USAGE_RECORDS,
            }
