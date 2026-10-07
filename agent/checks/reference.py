"""Pure-Python reference for the Cash Schedule totals block.

Reproduces the sample output's formulas (Cash Schedule rows 181-233) bucket by
bucket, from the raw orderbook lines. The validator compares the agent's
recalculated workbook with this; it never trusts the workbook's own totals.

Excel semantics mirrored here: SUMIFS with a date criterion skips text cells,
so "PM fees" lines never count on the PO side.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from agent.workbook.buckets import Bucket, month_groups
from agent.workbook.reader import OrderLine

# Row labels exactly as in the sample's Cash Schedule, keyed by field name. "{company}" is the
# portfolio company's name (see row_labels); field names keep "inceptua" for history only.
ROW_LABELS = {
    "outflows": "Total Supplier Purchases (Cash Outflows)",
    "inflows": "Total Customer Payments (Cash Inflows)",
    "net_operating": "Grand Total",
    "loan_draws": "New Loan Draws",
    "cash_investment": "{company} Cash Investment (excl. VAT)",
    "project_investment": "Total Supplier Purchases (Project Investment)",
    "net_inceptua": "Net {company} Cash Inflow (Outflow)",
    "customer_payments": "Total Customer Payments",
    "loan_repayments": "(-) Loan Repayments",
    "inceptua_cash": "{company} Cash",
    "loans_bop": "Loans - BoP",
    "loans_eop": "Loans - EoP",
    "bank_bop": "Bank Cash - BoP",
    "bank_eop": "Bank Cash - EoP",
    "invested_bop": "Cash Investment - BoP",
    "invested_eop": "Cash Investment - EoP",
    "total_cash": "Total Cash",
    "orderbook_value": "Total Project Value (Orderbook)",
    "net_debt": '"Net Debt"',
}
FLOW_FIELDS = ("outflows", "inflows", "net_operating", "loan_draws", "cash_investment", "project_investment",
               "net_inceptua", "customer_payments", "loan_repayments", "inceptua_cash")
BALANCE_FIELDS = ("loans_bop", "loans_eop", "bank_bop", "bank_eop", "invested_bop", "invested_eop",
                  "total_cash", "orderbook_value", "net_debt")


@dataclass
class Assumptions:
    model_start_date: date
    po_advance_rate: float
    opening_loan_balance: float
    opening_bank_cash: float  # total bank cash, Cash!I29 for Inceptua (the sample used I28; docs/NEXT_STEPS.md, question 10)


@dataclass
class ScheduleResult:
    buckets: list[Bucket]
    rows: dict[str, list[float]] = field(default_factory=dict)  # field -> value per bucket
    grand_total: dict[str, float] = field(default_factory=dict)  # flow fields only

    def column(self, i: int) -> dict[str, float]:
        return {k: v[i] for k, v in self.rows.items()}


def _within(d, start: date | None, end: date | None) -> bool:
    if not isinstance(d, (date, datetime)):
        return False
    d = d.date() if isinstance(d, datetime) else d
    return (start is None or d >= start) and (end is None or d < end)


def cash_schedule(lines: list[OrderLine], buckets: list[Bucket], a: Assumptions) -> ScheduleResult:
    res = ScheduleResult(buckets, {k: [] for k in ROW_LABELS})
    total_sales = sum(l.sales for l in lines)
    prev = None
    for b in buckets:
        in_b = lambda d: _within(d, b.start, b.end)  # noqa: E731
        outflows = -sum(l.purchase for l in lines if in_b(l.po_date))
        inflows = sum(l.sales for l in lines if in_b(l.so_date))
        inceptua_cash = sum(l.gp for l in lines if in_b(l.so_date))
        if b.kind == "catchup":
            # Financing lines only count activity from the model start date (sample behaviour).
            po_window = sum(l.purchase for l in lines if _within(l.po_date, a.model_start_date, b.end))
            draws = a.po_advance_rate * po_window
            investment = po_window - draws
            customer_payments = sum(l.sales for l in lines if _within(l.so_date, a.model_start_date, b.end))
            bank_purchases = -po_window
        else:
            draws = -a.po_advance_rate * outflows
            investment = -outflows - draws
            customer_payments = inflows
            bank_purchases = outflows
        repayments = inceptua_cash - customer_payments
        loans_bop = a.opening_loan_balance if prev is None else prev["loans_eop"]
        bank_bop = a.opening_bank_cash if prev is None else prev["bank_eop"]
        invested_bop = 0.0 if prev is None else prev["invested_eop"]
        loans_eop = loans_bop + repayments + draws
        bank_eop = bank_bop + customer_payments + draws + bank_purchases + repayments
        invested_eop = invested_bop - customer_payments
        orderbook_value = (total_sales if prev is None else prev["orderbook_value"]) - inflows
        col = {
            "outflows": outflows, "inflows": inflows, "net_operating": outflows + inflows,
            "loan_draws": draws, "cash_investment": investment, "project_investment": draws + investment,
            "net_inceptua": outflows + inflows + draws + repayments,
            "customer_payments": customer_payments, "loan_repayments": repayments, "inceptua_cash": inceptua_cash,
            "loans_bop": loans_bop, "loans_eop": loans_eop, "bank_bop": bank_bop, "bank_eop": bank_eop,
            "invested_bop": invested_bop, "invested_eop": invested_eop,
            "total_cash": bank_eop + invested_eop, "orderbook_value": orderbook_value,
            "net_debt": bank_eop + invested_eop - loans_eop,
        }
        for k, v in col.items():
            res.rows[k].append(v)
        prev = col
    res.grand_total = {k: sum(res.rows[k]) for k in FLOW_FIELDS}
    # The sample's Grand Total for inflows/outflows sums the whole orderbook, not the buckets.
    res.grand_total["outflows"] = -sum(l.purchase for l in lines)
    res.grand_total["inflows"] = total_sales
    return res


SUMMARY_FLOWS = {  # summary-tab label -> schedule field
    "Customer Payments (inflows)": "inflows",
    "Supplier Purchases (outflows)": "outflows",
    "Net Operating Cash Flow": "net_operating",
    "New Loan Draws": "loan_draws",
    "Loan Repayments": "loan_repayments",
    "Net {company} Cash Flow": "net_inceptua",
}
SUMMARY_BALANCES = {
    "Loans Outstanding": "loans_eop",
    "Bank Cash": "bank_eop",
    "Invested (Project) Cash": "invested_eop",
    "Net Debt": "net_debt",
}


def row_labels(company: str) -> dict[str, str]:
    return {k: v.replace("{company}", company) for k, v in ROW_LABELS.items()}


def summary_labels(company: str) -> tuple[dict[str, str], dict[str, str]]:
    """(flows, balances): summary-tab label -> schedule field, with the company's name filled in."""
    return {k.replace("{company}", company): v for k, v in SUMMARY_FLOWS.items()}, dict(SUMMARY_BALANCES)


def weekly_summary(s: ScheduleResult, company: str = "Inceptua") -> dict[str, list[float]]:
    """Cash Summary (Weekly) rows in EUR 000s, one value per bucket."""
    flows, balances = summary_labels(company)
    return {label: [v / 1000 for v in s.rows[f]] for label, f in {**flows, **balances}.items()}


def monthly_summary(s: ScheduleResult, company: str = "Inceptua") -> tuple[list[str], dict[str, list[float]]]:
    """Cash Summary (Monthly): flows sum the month's weeks, balances take its last week."""
    groups = month_groups(s.buckets)
    flows, balances = summary_labels(company)
    out: dict[str, list[float]] = {}
    for label, f in flows.items():
        out[label] = [sum(s.rows[f][i] for i in idx) / 1000 for _, idx in groups]
    for label, f in balances.items():
        out[label] = [s.rows[f][idx[-1]] / 1000 for _, idx in groups]
    return [g for g, _ in groups], out
