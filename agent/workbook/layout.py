"""The sample output's exact layout: every label, header and note, per generated tab.

Single source for devtools/reference_builder.py (writes it) and agent/checks/validate.py
(checks it), so the output always has the structure of the assignment's sample
vClaude file: same tabs, rows, columns and wording, nothing added. Only values
that depend on the week (dates, CW numbers, customer names) and the company's
name vary. Labels holding the name use the ``{company}`` placeholder; fill it with
``named()`` (every portfolio company sends the same template, ADR-0017).
"""
from __future__ import annotations

from datetime import date, timedelta

from agent.workbook.buckets import Bucket, month_groups

MONEY = '#,##0;\\(#,##0\\);\\–'  # summary tabs
CMP_MONEY = '#,##0;\\(#,##0\\);\\-'  # comparison tab
CMP_PCT = '0.0%;\\(0.0%\\);\\-'
CMP_PPT = '\\+0.0;\\-0.0;\\-'
SCHED_MONEY = '#,##0_);\\(#,##0\\);"- "'


COMPANY = "{company}"


def named(label: str | None, company: str) -> str | None:
    """Fill the company placeholder, e.g. "Net {company} Cash Flow" -> "Net Inceptua Cash Flow"."""
    return label.replace(COMPANY, company) if label else label


def d_mon(d: date) -> str:
    return f"{d.day} {d:%b}"  # "4 Sep"


def mdy(d: date, full_year: bool = False) -> str:
    """US short date as in the sample: 8/28/26 (or 9/4/2026)."""
    return f"{d.month}/{d.day}/{d.year}" if full_year else f"{d.month}/{d.day}/{d.year % 100:02d}"


# --------------------------------------------------------------------------- summaries
SUMMARY_ROWS = {  # row -> (label, Cash Schedule field)
    7: ("Customer Payments (inflows)", "inflows"),
    8: ("Supplier Purchases (outflows)", "outflows"),
    9: ("Net Operating Cash Flow", "net_operating"),
    11: ("New Loan Draws", "loan_draws"),
    12: ("Loan Repayments", "loan_repayments"),
    13: ("Net {company} Cash Flow", "net_inceptua"),
    16: ("Loans Outstanding", "loans_eop"),
    17: ("Bank Cash", "bank_eop"),
    18: ("Invested (Project) Cash", "invested_eop"),
    19: ("Net Debt", "net_debt"),
}
FLOW_ROWS = (7, 8, 9, 11, 12, 13)
BALANCE_ROWS = (16, 17, 18, 19)


def weekly_labels(company: str, cw: int, year: int, report: date, buckets: list[Bucket]) -> dict[str, object]:
    weeks = [b for b in buckets if b.kind == "week"]
    first, last = weeks[0].label.split()[0], weeks[-1].label.split()[0]
    cells: dict[str, object] = {
        "A1": f"{company} — Weekly Cash Flow & Net Debt Summary",
        "A2": f"CW{cw:02d} {year} report  •  catch-up through {report.day} {report:%b %Y}, then ISO weeks "
              f"{first}–{last}  •  € thousands (€000s)",
        "A4": "€000s", "A5": "Week ending →",
        "A6": "OPERATING CASH FLOWS & FINANCING", "A15": "PERIOD-END BALANCES",
        "A21": "Notes:",
        "A22": "•  Figures in € thousands. Negatives in parentheses; zero shown as –.",
        "A23": "•  Grand Total applies to flow lines only; period-end balances are point-in-time and do not total across weeks.",
        "A24": f"•  Catch-up column aggregates all payments through {report.day} {report:%b %Y}; later columns are ISO weeks "
               "(Mon–Sun), labelled by week-ending date.",
        "A25": "•  Source: 'Cash Schedule' tab (live-linked).",
    }
    for r, (label, _) in SUMMARY_ROWS.items():
        cells[f"A{r}"] = named(label, company)
    return cells


def weekly_headers(cw: int, buckets: list[Bucket]) -> list[tuple[str, str]]:
    """(row 4, row 5) text for columns B.. : catch-up, weeks, After, Grand Total."""
    out = []
    for b in buckets:
        if b.kind == "catchup":
            out.append((f"CW{cw:02d}", d_mon(b.week_ending)))
        elif b.kind == "week":
            out.append((b.label, d_mon(b.week_ending)))
        else:
            out.append(("After", buckets[-2].label.split()[0]))
    out.append(("Grand", "Total"))
    return out


def monthly_labels(company: str, cw: int, year: int, report: date) -> dict[str, object]:
    cells: dict[str, object] = {
        "A1": f"{company} — Monthly Cash Flow & Net Debt Summary",
        "A2": f"CW{cw:02d} {year} report  •  weeks rolled into calendar months  •  € thousands (€000s)",
        "A4": "€000s",
        "A6": "OPERATING CASH FLOWS & FINANCING", "A15": "MONTH-END BALANCES",
        "A21": "Notes:",
        "A22": "•  Figures in € thousands. Negatives in parentheses; zero shown as –.",
        "A23": "•  Weeks are grouped into calendar months by week-ending date. Flow lines sum the weeks in each month; "
               "month-end balances take the last week's value in the month.",
        "A24": f"•  'Through {d_mon(report)}' is the catch-up bucket (all activity to the CW{cw:02d} report date); "
               "'After' captures any activity beyond the last modelled week.",
        "A25": "•  Grand Total applies to flow lines only; month-end balances are point-in-time. "
               "Source: 'Cash Schedule' tab (live-linked).",
    }
    for r, (label, _) in SUMMARY_ROWS.items():
        cells[f"A{r}"] = named(label, company)
    return cells


def monthly_headers(buckets: list[Bucket]) -> list[tuple[str, str]]:
    """(row 4, row 5) text for columns B.. : Through, months, After, Grand Total."""
    out = []
    last_week = buckets[-2].week_ending
    for label, idx in month_groups(buckets):
        b = buckets[idx[0]]
        if b.kind == "catchup":
            out.append(("Through", d_mon(b.week_ending)))
        elif b.kind == "after":
            out.append(("After", f"{last_week:%b} {last_week.year % 100:02d}"))
        else:
            out.append((f"{buckets[idx[-1]].week_ending:%b}", str(buckets[idx[-1]].week_ending.year)))
    out.append(("Grand", "Total"))
    return out


# --------------------------------------------------------------------------- comparison tab
CUSTOMER_ROWS = 9  # the sample lists the 9 largest CDS customer rows (Customer-Level order), "Others" included
OTHERS_LABEL = {"Others": "Others (small accounts)"}

# row -> (metric key or None for a section/title line, label). Customer rows 19-27 are filled separately.
COMPARISON_ROWS = {
    6: (None, "GROUP P&L — YTD (Invoiced + Orderbook)"),
    7: ("adj_revenue", "Total Adjusted Revenue**"),
    8: ("invoiced_gp", "Invoiced Gross Profit"),
    9: ("orderbook_gp", "Orderbook Gross Profit"),
    10: ("total_gp", "Total Gross Profit (I+OB)"),
    11: ("gm_pct", "% Gross Margin (I+OB)"),
    12: ("gp_budget_pct", None),  # "GP as % of FY26 Budget (€34.4M)", built from the budget
    13: ("adj_revenue_budget_pct", None),  # "Adj. Revenue as % of FY26 Budget"
    14: (None, "GROSS PROFIT BY SEGMENT — YTD (Invoiced + Orderbook)"),
    15: ("gp_cds", "Comparator Drug Sourcing"),
    16: ("gp_cs", "Clinical Services"),
    17: ("gp_ea", "Early Access Program Fees"),
    18: (None, "KEY CUSTOMER MOVES — CDS GP, YTD (Invoiced + Orderbook)"),
    28: (None, "TOTAL OUTSTANDING ORDERBOOK — CDS, open orders at snapshot (€K)"),
    29: ("open_orders", "# Open Orders (unique sales orders)"),
    30: ("open_sales", "Open Sales Orders (revenue)"),
    31: ("open_purchases", "Open Purchase Orders (cost)"),
    32: ("orderbook_cash_gp", "Outstanding Orderbook GP"),
    33: ("orderbook_margin_pct", "Implied Orderbook GP Margin"),
    34: (None, None),  # "CASH & DEBT (snapshot dates 8/26/26 vs. 9/2/26)"
    35: ("cash_incl_pharma", "Total Group Cash (incl. Pharma Model)"),
    36: ("total_debt", "Total Debt"),
    37: ("net_debt_incl_pharma", "Net Debt (incl. Pharma Model)"),
}
PCT_KEYS = {"gm_pct", "gp_budget_pct", "adj_revenue_budget_pct", "orderbook_margin_pct"}
CUSTOMER_FIRST_ROW = 19
FOOTNOTE_ROW = 39


def comparison_fixed_labels(company: str, cw: int, year: int, report: date, prior_report: date, cash: date, prior_cash: date,
                            gp_budget_k: float | None, prior_files: str) -> dict[str, str]:
    p = cw - 1
    yy = year % 100
    cells = {
        "B2": comparison_title(company, cw),
        "B3": f"YTD figures in Thousands of EUR  |  CW{p:02d} YTD through {mdy(prior_report)}  |  CW{cw:02d} YTD through "
              f"{mdy(report)}  |  CW{cw:02d} figures live-linked to source tabs; CW{p:02d} = prior-week snapshot",
        "B5": "Metric", "C5": f"CW{p:02d}", "D5": f"CW{cw:02d}", "E5": "W/W Change", "F5": "W/W %",
        "G5": "Comment (refresh as needed)",
        "B12": f"GP as % of FY{yy} Budget ({f'€{gp_budget_k / 1000:.1f}M' if gp_budget_k else 'n/a'})",
        "B13": f"Adj. Revenue as % of FY{yy} Budget",
        "B34": f"CASH & DEBT (snapshot dates {mdy(prior_cash)} vs. {mdy(cash)})",
        "B39": "** Excludes Early Access pass-through revenues and COGS. Total Outstanding Orderbook = open (undelivered) "
               "CDS sales orders, purchase orders, GP, and order count at each snapshot (a point-in-time balance, not YTD "
               "flow). All figures read directly from source cells (Summary col F = I+OB GP, Customer-Level col J = "
               f"customer I+OB GP), cross-checked to segment totals. Source files: {prior_files}.",
    }
    for r, (_, label) in COMPARISON_ROWS.items():
        if label:
            cells[f"B{r}"] = label
    return cells


def comparison_title(company: str, cw: int) -> str:
    return f"{company} Trading Update — CW{cw:02d} vs. CW{cw - 1:02d} Comparison"


# --------------------------------------------------------------------------- Cash Schedule
# Totals block: offset from the "Total, Net" row (sample: 179 -> 181, 182, ...). Labels as in the sample.
SCHEDULE_OFFSETS = {
    "total_net": (0, "Total, Net"),
    "outflows": (2, "Total Supplier Purchases (Cash Outflows)"),
    "inflows": (3, "Total Customer Payments (Cash Inflows)"),
    "net_operating": (4, "Grand Total"),
    "loan_draws": (6, "New Loan Draws"),
    "cash_investment": (7, "{company} Cash Investment (excl. VAT)"),
    "project_investment": (8, "Total Supplier Purchases (Project Investment)"),
    "net_inceptua": (10, "Net {company} Cash Inflow (Outflow)"),
    "customer_payments": (12, "Total Customer Payments"),
    "loan_repayments": (13, "(-) Loan Repayments"),
    "inceptua_cash": (14, "{company} Cash"),
    "summary_view": (16, "Bank Cash - Summary View"),
    "summary_loans": (17, "Loans"),
    "loan_schedule": (26, "Loan Schedule"),
    "loans_bop": (27, "Loans - BoP"),
    "loans_repay": (28, "(-) Repayments"),
    "loans_draws": (29, "(+) New Draws"),
    "loans_eop": (30, "Loans - EoP"),
    "bank_schedule": (32, "Bank Cash Schedule"),
    "bank_bop": (33, "Bank Cash - BoP"),
    "bank_completed": (34, "(+) Payment from Completed Projects"),
    "bank_draws": (35, "(+) New Loan Draws"),
    "bank_purchases": (36, "(-) Supplier Purchases"),
    "bank_repay": (37, "(-) Loan Repayment"),
    "bank_blank": (38, None),
    "bank_eop": (39, "Bank Cash - EoP"),
    "invested_schedule": (41, "Cash Investment - Schedule"),
    "invested_bop": (42, "Cash Investment - BoP"),
    "invested_completed": (43, "(-) Payment from Completed Projects, net of Loan Repayment"),
    "invested_new": (44, "(+) New Project Investment"),
    "invested_eop": (45, "Cash Investment - EoP"),
    "total_bank": (47, "Bank Cash"),
    "total_invested": (48, "Invested Cash"),
    "total_cash": (49, "Total Cash"),
    "total_loans": (51, "Loans"),
    "orderbook_value": (52, "Total Project Value (Orderbook)"),
    "net_debt": (54, '"Net Debt"'),
    "notes": (58, "Notes:"),
}
NOTE_LINES = 3


def schedule_offsets(company: str) -> dict[str, tuple[int, str | None]]:
    """SCHEDULE_OFFSETS with the company's name filled in."""
    return {k: (off, named(label, company)) for k, (off, label) in SCHEDULE_OFFSETS.items()}  # rows T+59 .. T+61
SPACER_COLUMNS = 2


def schedule_notes(first_row: int, last_row: int, cols: dict[str, str | None], report: date, buckets: list[Bucket],
                   sheet: str = "Orderbook CDS") -> list[str]:
    weeks = [b for b in buckets if b.kind == "week"]
    c = {k: v or "n/a" for k, v in cols.items()}
    return [
        "- Values shown are: Open Purchase EUR (on PO Forecasted Payment Date) + Open Sales EUR (on SO Forecasted Payment Date)",
        f"- Data source: '{sheet}' sheet, rows {first_row}-{last_row}; col {c.get('customer', 'n/a')}=Customer, "
        f"col {c.get('item', 'n/a')}=Item, col {c['sales']}=Open Sales EUR, col {c['purchase']}=Open Purchase EUR, "
        f"col {c['gp']}=GP EUR, col {c.get('gp_pct', 'n/a')}=GP %, col {c['so_date']}=SO Pay Date, col {c['po_date']}=PO Pay Date",
        f"- Date range: weekly buckets — catch-up through {mdy(report, full_year=True)}, then ISO weeks {weeks[0].label} "
        f"through {weeks[-1].label}, plus an 'After' catch-all",
    ]


def daily_grid_end(buckets: list[Bucket]) -> date:
    """Last day of the month after the last forward week's month (sample: week ending 21 Mar -> 30 Apr)."""
    last = buckets[-2].week_ending
    first_of_next_next = (last.replace(day=1) + timedelta(days=62)).replace(day=1)
    return first_of_next_next - timedelta(days=1)
