"""Headline metrics read from a trading-update workbook.

One definition used everywhere: the validator (expected values on the
CWnn vs CWnn-1 tab), the evals, and later metrics.json for the dashboard.
All values in EUR thousands unless the key ends in ``_pct``.
"""
from __future__ import annotations

from agent.workbook.reader import TradingUpdate

# key -> label (or label prefix) on the comparison tab, column B. Order = row order.
PNL_LABELS = {
    "adj_revenue": "Total Adjusted Revenue**",
    "invoiced_gp": "Invoiced Gross Profit",
    "orderbook_gp": "Orderbook Gross Profit",
    "total_gp": "Total Gross Profit (I+OB)",
    "gm_pct": "% Gross Margin (I+OB)",
    "gp_budget_pct": "GP as % of FY",  # prefix: "GP as % of FY26 Budget"
    "adj_revenue_budget_pct": "Adj. Revenue as % of FY",
    "gp_cds": "Comparator Drug Sourcing",
    "gp_cs": "Clinical Services",
    "gp_ea": "Early Access Program Fees",
    "open_orders": "# Open Orders (unique sales orders)",
    "open_sales": "Open Sales Orders (revenue)",
    "open_purchases": "Open Purchase Orders (cost)",
    "orderbook_cash_gp": "Outstanding Orderbook GP",
    "orderbook_margin_pct": "Implied Orderbook GP Margin",
    "cash_incl_pharma": "Total Group Cash (incl. Pharma Model)",
    "total_debt": "Total Debt",
    "net_debt_incl_pharma": "Net Debt (incl. Pharma Model)",
}


def headline(tu: TradingUpdate) -> dict[str, float | None]:
    """Located through the company's source map. An input the file doesn't have gives None (shown as n/a)."""
    total = tu.segment("total")
    adj_rev = tu.summary("adj_revenue")
    total_gp = total["iob_gp"]
    gp_budget, rev_budget = tu.summary("total_gp", budget=True), tu.summary("adj_revenue", budget=True)
    seg = lambda k: (tu.segment(k) or {}).get("iob_gp")  # noqa: E731
    lines = tu.orderbook()
    sales = sum(l.sales for l in lines) / 1000
    ob_gp = sum(l.gp for l in lines if l.so_date is not None) / 1000
    bs = tu.balance_sheet("current")
    return {
        "adj_revenue": adj_rev,
        "invoiced_gp": total["inv_gp"],
        "orderbook_gp": total["ob_gp"],
        "total_gp": total_gp,
        "gm_pct": None if adj_rev is None else (total_gp / adj_rev if adj_rev else 0.0),
        "gp_budget_pct": total_gp / gp_budget if gp_budget else None,
        "adj_revenue_budget_pct": adj_rev / rev_budget if adj_rev is not None and rev_budget else None,
        "gp_cds": seg("cds"),
        "gp_cs": seg("cs"),
        "gp_ea": seg("ea"),
        "open_orders": float(len({l.so for l in lines})),
        "open_sales": sales,
        "open_purchases": sum(l.purchase for l in lines) / 1000,
        "orderbook_cash_gp": ob_gp,
        "orderbook_margin_pct": ob_gp / sales if sales else 0.0,
        "cash_incl_pharma": bs["cash_incl_pharma"],
        "total_debt": bs["debt"],
        "net_debt_incl_pharma": bs["net_debt_incl_pharma"],
    }


def customer_gp(tu: TradingUpdate) -> dict[str, float]:
    return {name: v["iob_gp"] for name, v in tu.cds_customers().items()}


def prior_from_history(tu: TradingUpdate) -> dict[str, float]:
    """Best-effort prior-week values from the current file's own history (ADR-0005 fallback).

    Only GP (Weekly GP tab) and cash/debt (Customer-Level column H) have history;
    everything else is absent and must be reported as n/a.
    """
    _, cw = tu.iso_week
    out: dict[str, float] = {}
    hist = tu.weekly_gp(cw - 1)
    if hist:
        out.update({
            "invoiced_gp": hist["inv_gp_total"],
            "orderbook_gp": hist["ob_gp_total"],
            "total_gp": hist["iob_gp_total"],
            "gp_cds": hist["iob_gp_cds"],
        })
        out.update({k: hist[f"iob_gp_{s}"] for k, s in (("gp_cs", "cs"), ("gp_ea", "ea")) if tu.segment(s)})
    bs = tu.balance_sheet("prior")
    if bs:
        out.update({"cash_incl_pharma": bs["cash_incl_pharma"], "total_debt": bs["debt"],
                    "net_debt_incl_pharma": bs["net_debt_incl_pharma"]})
    return out
