from concurrent.futures import ThreadPoolExecutor
from time import sleep

import pytest

from kaykay.core import Gateway, Request


def test_fallback():
    gateway = Gateway({"bad": lambda request: 1 / 0, "good": lambda request: "ok"}, {"m": .001}, .01)
    assert gateway.complete(Request("k", "m", "hello", 1)).provider == "good"


def test_budget():
    gateway = Gateway({"p": lambda request: "ok"}, {"m": 1}, .001)
    with pytest.raises(RuntimeError, match="budget_exceeded"):
        gateway.complete(Request("k", "m", "hello", 100))


def test_unknown_model_and_bad_token_count_are_rejected():
    gateway = Gateway({"p": lambda request: "ok"}, {"known": .001}, 1)
    with pytest.raises(RuntimeError, match="unknown_model"):
        gateway.complete(Request("k", "unknown", "hello", 10))
    with pytest.raises(RuntimeError, match="invalid_max_tokens"):
        gateway.complete(Request("k", "known", "hello", 99999))


def test_concurrent_reservations_never_overspend():
    def provider(request):
        sleep(.01)
        return "ok"

    gateway = Gateway({"p": provider}, {"m": .01}, budget=.0002)
    request = Request("k", "m", "one", max_tokens=1)
    with ThreadPoolExecutor(max_workers=12) as pool:
        outcomes = list(pool.map(lambda _: _call(gateway, request), range(12)))
    assert outcomes.count("success") == 1
    assert gateway.spent <= gateway.budget
    assert gateway.reserved == 0


def _call(gateway, request):
    try:
        gateway.complete(request)
        return "success"
    except RuntimeError as exc:
        assert str(exc) == "budget_exceeded"
        return "rejected"


def test_usage_history_is_bounded():
    gateway = Gateway({"p": lambda request: "ok"}, {"m": 0}, budget=1)
    for _ in range(gateway.MAX_USAGE_RECORDS + 2):
        gateway.complete(Request("k", "m", "hello", 1))
    assert len(gateway.usage) == gateway.MAX_USAGE_RECORDS
