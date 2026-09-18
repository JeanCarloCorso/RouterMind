from decimal import Decimal

from conftest import model
from app.services.cost_estimator import estimate_cost, is_free, parse_price


def test_free_requires_all_components_zero():
    assert is_free(model("free"))
    item = model("not-free")
    item["pricing"]["request"] = "0.01"
    assert not is_free(item)


def test_cost_includes_input_output_and_request_fee():
    item = model("paid", "0.001", "0.002")
    item["pricing"]["request"] = "0.1"
    estimate = estimate_cost({"messages": [{"role": "user", "content": "abc"}], "max_tokens": 10}, item, 100)
    assert estimate is not None
    assert estimate.usd == Decimal("0.1") + Decimal("0.001") * estimate.input_tokens + Decimal("0.02")


def test_unknown_prices_and_paid_plugins_are_rejected():
    assert parse_price(None) is None
    assert parse_price("unknown") is None
    assert parse_price("-1") is None
    item = model("bad")
    item["pricing"]["prompt"] = None
    assert estimate_cost({"messages": []}, item, 10) is None
    assert estimate_cost({"messages": [], "plugins": [{"id": "web"}]}, model("free"), 10) is None


def test_null_max_tokens_uses_safe_default():
    estimate = estimate_cost({"messages": [], "max_tokens": None}, model("free"), 77)
    assert estimate is not None
    assert estimate.output_tokens == 77
