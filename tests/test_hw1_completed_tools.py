"""Offline regression checks for HW1 scope and state-changing contracts."""

from types import SimpleNamespace

import pytest

from agent import db, tools
from agent.auth import AuthContext


SHOPPER = AuthContext(user_id=1, role="shopper")


def test_cancel_denies_before_disclosing_status_and_enforces_cutoff_for_support(world_copy):
    merchant = AuthContext(user_id=9002, role="merchant", store_id=2)
    denied = tools.cancel_order(merchant, 4127, "cancel it")
    assert denied["error"] == "permission_denied"
    assert "merchant" in denied["reason"] and "4127" in denied["reason"]
    assert "delivered" not in denied["reason"]

    support = AuthContext(user_id=9501, role="support")
    ineligible = tools.cancel_order(support, 4127, "cancel it")
    assert ineligible["error"] == "not_eligible"
    assert "delivered" in ineligible["reason"]
    with db.connection() as conn:
        assert db.get_order(conn, 4127).status == "delivered"


def test_cancel_kill_switch_prevents_database_access(monkeypatch):
    monkeypatch.setenv("CARTWHEEL_KILL_SWITCH", "readonly")

    def forbidden_connection():
        pytest.fail("paused cancellation must not access the database")

    monkeypatch.setattr(db, "connection", forbidden_connection)
    assert tools.cancel_order(SHOPPER, 4127, "cancel it")["error"] == "paused"


@pytest.mark.parametrize(
    "ctx",
    [
        SimpleNamespace(user_id=1, role="admin", store_id=None),
        SimpleNamespace(user_id=None, role="shopper", store_id=None),
        SimpleNamespace(user_id=9002, role="merchant", store_id=None),
        SimpleNamespace(user_id=None, role="support", store_id=None),
    ],
)
@pytest.mark.parametrize(
    "tool,args",
    [
        (tools.find_order, ("mug",)),
        (tools.list_my_orders, ()),
        (tools.cancel_order, (4127, "cancel it")),
    ],
)
def test_private_order_tools_fail_closed_for_incomplete_context(ctx, tool, args, monkeypatch):
    monkeypatch.setenv("CARTWHEEL_KILL_SWITCH", "off")

    def forbidden_connection():
        pytest.fail("invalid authenticated scope must not access the database")

    monkeypatch.setattr(db, "connection", forbidden_connection)
    assert tool(ctx, *args)["error"] == "permission_denied"


def test_product_filters_limit_and_price_tiebreaker(world_copy):
    with db.connection() as conn:
        product_ids = [product.id for product in db.list_products(conn, store_id=1)[:30]]
        for index, product_id in enumerate(product_ids):
            conn.execute(
                "UPDATE products SET title = ?, description = ?, price_cents = ? WHERE id = ?",
                ("hw1contract", "Exact description", 1000 + (index % 3) * 100, product_id),
            )
        conn.commit()

    result = tools.search_products(
        SHOPPER, "HW1contract DESCRIPTION", store="blue-heron-ceramics", max_price_usd=11, limit=99
    )
    expected = sorted(
        (10 + index % 3, product_id)
        for index, product_id in enumerate(product_ids)
        if index % 3 <= 1
    )
    assert [(p["price_usd"], p["product_id"]) for p in result["products"]] == expected
    assert result["count"] == 20
    assert tools.search_products(SHOPPER, "hw1contract", limit=0)["count"] == 1
    assert tools.search_products(SHOPPER, "hw1contract", limit=100)["count"] == 25
    for ceiling in (0, -1, float("nan")):
        assert tools.search_products(SHOPPER, "hw1contract", max_price_usd=ceiling)["error"] == "invalid_argument"


def test_find_order_accepts_conversational_product_description(order_search_cases):
    title, expected = order_search_cases
    result = tools.find_order(SHOPPER, f"Can you find the {title} I bought last week?")
    assert [order["order_id"] for order in result["orders"]] == expected["shopper"][:5]
    assert tools.find_order(SHOPPER, "   ") == {"ok": True, "orders": []}


@pytest.mark.parametrize(
    "ctx",
    [SHOPPER, AuthContext(user_id=9002, role="merchant", store_id=2), AuthContext(user_id=9501, role="support")],
)
def test_store_info_is_public_and_respects_the_override(world, ctx):
    default = tools.get_store_info(ctx, "BLUE HERON CERAMICS")["store"]
    assert default == {
        "store_id": 1,
        "name": "Blue Heron Ceramics",
        "category": "home_and_kitchen",
        "return_window_days_override": None,
        "effective_return_window_days": 30,
        "restocking_fee_opt_in": False,
        "policy_ids": ["cw-returns"],
    }
    override = tools.get_store_info(ctx, "juniper-home-goods")["store"]
    assert override["store_id"] == 2
    assert override["return_window_days_override"] == 14
    assert override["effective_return_window_days"] == 14
    assert override["policy_ids"] == ["cw-returns", "store-juniper-home-goods-policy"]
    assert set(override) == set(default)


def test_store_info_reports_bad_input_and_uses_configured_default(world, monkeypatch):
    assert tools.get_store_info(SHOPPER, "   ")["error"] == "invalid_argument"
    assert tools.get_store_info(SHOPPER, "unknown-store")["error"] == "not_found"
    monkeypatch.setattr(tools, "load_facts", lambda: {"return_window_days": 45})
    assert tools.get_store_info(SHOPPER, "Blue Heron Ceramics")["store"]["effective_return_window_days"] == 45
    assert tools.get_store_info(SHOPPER, "Juniper Home Goods")["store"]["effective_return_window_days"] == 14
