"""The dashboard's data layer: reads only metrics.json files, state.json and the service's heartbeat.json (ADR-0010).

No Streamlit here, so everything is testable. The app (dashboard/app.py) only renders.

A company's reports are every ``*.metrics.json`` under ``ROOT/<company>``. Weekly
pipeline companies (Inceptua) write the full schema from agent.publishing.report_metrics;
dashboard-only companies write a smaller one with a ``kpis`` list. When a week was
resent, only its latest revision is shown. All money is in EUR thousands.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from agent import heartbeat
from agent.config import Company, Config

SEGMENT_NAMES = {"cds": "Comparator Drug Sourcing", "cs": "Clinical Services", "ea": "Early Access"}


@dataclass
class Report:
    """One period's metrics.json, with the files next to it."""
    metrics: dict
    path: Path  # the metrics.json file

    @property
    def label(self) -> str:
        m = self.metrics
        return f"CW{m['cw']:02d} {m['year']}" if "cw" in m else m.get("period_label", m["report_date"])

    @property
    def sort_key(self) -> tuple:
        return (self.metrics["report_date"], self.metrics.get("revision", 1))

    @property
    def period(self) -> tuple:
        m = self.metrics
        return (m["year"], m["cw"]) if "cw" in m else (m.get("period_label"),)

    def file(self, key: str) -> Path | None:
        """The source or output workbook next to this metrics.json, if it exists."""
        name = self.metrics.get(key)
        p = self.path.with_name(name) if name else None
        return p if p and p.exists() else None

    @property
    def built_by(self) -> str:
        return "reference builder (no Claude)" if self.metrics.get("builder") == "reference" else "Claude"


@dataclass
class Kpi:
    label: str
    value: float | None
    prior: float | None = None
    unit: str = "eur_k"  # eur_k | pct | count
    help: str = ""

    @property
    def change(self) -> float | None:
        if self.value is None or self.prior is None:
            return None
        return self.value - self.prior


@dataclass
class RunEntry:
    at: str
    subject: str
    sender: str
    status: str
    detail: str = ""
    cost_usd: float | None = None


# --------------------------------------------------------------------------- loading
def load_reports(cfg: Config, company: Company) -> list[Report]:
    """Every period for the company, oldest first, latest revision per period."""
    folder = cfg.company_folder(company.key)
    latest: dict[tuple, Report] = {}
    for p in folder.rglob("*.metrics.json"):
        try:
            r = Report(json.loads(p.read_text(encoding="utf-8")), p)
            _ = r.sort_key, r.label
        except (json.JSONDecodeError, KeyError, OSError):
            continue  # a half-written or foreign file must not break the dashboard
        if r.period not in latest or r.sort_key > latest[r.period].sort_key:
            latest[r.period] = r
    return sorted(latest.values(), key=lambda r: r.sort_key)


def previous(reports: list[Report], current: Report) -> Report | None:
    # By period, not identity: after a cache refresh the selected Report is a different object.
    i = next((i for i, r in enumerate(reports) if r.period == current.period), 0)
    return reports[i - 1] if i > 0 else None


# --------------------------------------------------------------------------- Inceptua (full schema)
def headline_kpis(m: dict, prev: dict | None = None) -> list[Kpi]:
    """Headline KPIs. Prior = the report's own prior-week values, else last week's metrics.json."""
    h = m.get("headline", {})
    p = dict((prev or {}).get("headline", {}))
    p.update(m.get("prior", {}).get("values", {}))
    get = lambda k: p.get(k)  # noqa: E731
    return [
        Kpi("Adj. revenue YTD", h.get("adj_revenue"), get("adj_revenue"), help="Invoiced + orderbook, excl. EA pass-through"),
        Kpi("Gross profit YTD", h.get("total_gp"), get("total_gp"), help="Invoiced + orderbook (I+OB)"),
        Kpi("Gross margin", h.get("gm_pct"), get("gm_pct"), "pct", "Total GP / adj. revenue"),
        Kpi("GP vs FY budget", h.get("gp_budget_pct"), get("gp_budget_pct"), "pct", "Total GP / full-year GP budget"),
        Kpi("Group cash", h.get("cash_incl_pharma"), get("cash_incl_pharma"), help="Incl. Pharma Model"),
        Kpi("Net debt", h.get("net_debt_incl_pharma"), get("net_debt_incl_pharma"), help="Incl. Pharma Model"),
        Kpi("Open orderbook (sales)", h.get("open_sales"), get("open_sales"), help="Open CDS sales orders"),
        Kpi("Open orders", h.get("open_orders"), get("open_orders"), "count", "Unique CDS sales orders"),
    ]


def segment_rows(m: dict, prev: dict | None = None) -> list[dict]:
    """Revenue and GP by segment: YTD, W/W, prior year and budget (EUR k)."""
    seg, pseg = m.get("segments", {}), (prev or {}).get("segments", {})
    rows = []
    for key, name in {**SEGMENT_NAMES, "total": "Total"}.items():
        s, ps = seg.get(key), pseg.get(key, {})
        if not s:
            continue
        rev, gp = s["adj_revenue"], s["gp"]
        p_rev = ps.get("adj_revenue", {}).get("ytd")
        p_gp = ps.get("gp", {}).get("ytd")
        rows.append({
            "Segment": name,
            "Adj. revenue YTD": rev["ytd"],
            "Revenue W/W": _diff(rev["ytd"], p_rev),
            "Revenue vs PY": _pct(rev["ytd"], rev.get("py")),
            "Revenue % of budget": _ratio(rev["ytd"], rev.get("budget")),
            "GP YTD": gp["ytd"],
            "GP W/W": _diff(gp["ytd"], p_gp),
            "GP vs PY": _pct(gp["ytd"], gp.get("py")),
            "GP % of budget": _ratio(gp["ytd"], gp.get("budget")),
            "GP margin": _ratio(gp["ytd"], rev["ytd"]),
        })
    return rows


def customer_rows(m: dict, prev: dict | None = None) -> list[dict]:
    prev_gp = {c["name"]: c["iob_gp"] for c in (prev or {}).get("customers", [])}
    rows = []
    for c in m.get("customers", []):
        prior = c.get("prior_iob_gp")
        if prior is None:
            prior = prev_gp.get(c["name"])
        rows.append({"Customer": c["name"], "GP YTD (I+OB)": c["iob_gp"], "Invoiced GP": c["inv_gp"],
                     "Orderbook GP": c["ob_gp"], "Revenue YTD (I+OB)": c["iob_rev"],
                     "GP margin": _ratio(c["iob_gp"], c["iob_rev"]), "Prior week GP": prior,
                     "GP W/W": _diff(c["iob_gp"], prior)})
    return sorted(rows, key=lambda r: -r["GP YTD (I+OB)"])


def trend_rows(reports: list[Report], keys: dict[str, str]) -> list[dict]:
    """Headline values across weeks, long form: {Week, Metric, Value}."""
    out = []
    for r in reports:
        h = r.metrics.get("headline") or {k["key"]: k["value"] for k in r.metrics.get("kpis", [])}
        for key, label in keys.items():
            if h.get(key) is not None:
                out.append({"Week": r.label, "Date": r.metrics["report_date"], "Metric": label, "Value": h[key]})
    return out


def cash_summary_table(m: dict, basis: str) -> tuple[list[str], dict[str, list[float]]]:
    s = m.get("cash_summary", {}).get(basis, {})
    return s.get("labels", []), s.get("rows", {})


# --------------------------------------------------------------------------- generic companies
def generic_kpis(m: dict, prev: dict | None = None) -> list[Kpi]:
    prior = {k["key"]: k["value"] for k in (prev or {}).get("kpis", [])}
    return [Kpi(k["label"], k.get("value"), k.get("prior", prior.get(k["key"])), k.get("unit", "eur_k"), k.get("help", ""))
            for k in m.get("kpis", [])]


def generic_trend_keys(m: dict) -> dict[str, str]:
    return {k["key"]: k["label"] for k in m.get("kpis", []) if k.get("unit", "eur_k") == "eur_k"}


# --------------------------------------------------------------------------- run status
def inbox_status(cfg: Config) -> dict:
    """The service's inbox health from state.json: last_ok, and while failing: failures, failing_since, last_error."""
    try:
        return json.loads(cfg.state_file.read_text(encoding="utf-8")).get("inbox", {})
    except (OSError, json.JSONDecodeError):
        return {}


def service_status(cfg: Config, now: datetime | None = None) -> dict:
    """Is the service running? From its heartbeat.json: running | busy | stopped | not_running | unknown."""
    return heartbeat.read_status(cfg.state_file, now or datetime.now().astimezone())


def held_weeks(cfg: Config) -> list[dict]:
    """Weeks waiting for last week's report to be published (state.json "held", ADR-0023), oldest first."""
    try:
        held = json.loads(cfg.state_file.read_text(encoding="utf-8")).get("held", {})
    except (OSError, json.JSONDecodeError):
        return []
    rows = [{**h, "source": k} for k, h in held.items()]
    return sorted(rows, key=lambda h: (h.get("year", 0), h.get("cw", 0)))


def run_log(cfg: Config, company: Company, limit: int = 20) -> list[RunEntry]:
    """Emails the service handled for this company (state.json), newest first."""
    try:
        state = json.loads(cfg.state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    folder = str(cfg.company_folder(company.key)).lower()
    out = []
    for entry in state.get("processed", {}).values():
        if entry.get("status") == "preexisting":  # already in the inbox before a reset (devtools/reset_demo.py)
            continue
        runs = entry.get("runs", [])
        mine = any(str(r.get("output") or r.get("source") or "").lower().startswith(folder) for r in runs)
        if not mine and entry.get("sender", "").lower() not in company.senders:
            continue
        last = runs[-1] if runs else {}
        status = last.get("status", entry.get("status", "?"))
        detail = (last.get("reason") or entry.get("reason") or (Path(last["output"]).name if last.get("output") else "")
                  or (f"review {last['review_id']}" if last.get("review_id") else ""))
        out.append(RunEntry(entry.get("at", ""), entry.get("subject", ""), entry.get("sender", ""), status, detail,
                            last.get("cost_usd")))
    return sorted(out, key=lambda e: e.at, reverse=True)[:limit]


# --------------------------------------------------------------------------- helpers
def _diff(a, b):
    return None if a is None or b is None else a - b


def _ratio(a, b):
    return None if a is None or not b else a / b


def _pct(a, b):
    return None if a is None or not b else a / b - 1


# --------------------------------------------------------------------------- analysis for the memo-style pages
def prior_headline(m: dict, prev: dict | None = None) -> dict:
    """Last week's headline values: the report's own prior values first, then last week's metrics.json."""
    p = dict((prev or {}).get("headline", {}))
    p.update(m.get("prior", {}).get("values", {}))
    return p


def budget_coverage(m: dict) -> dict | None:
    """How much of the full-year GP budget is invoiced, and how much more the open orderbook adds."""
    gp = m.get("segments", {}).get("total", {}).get("gp", {})
    h = m.get("headline", {})
    budget = gp.get("budget")
    if not budget or h.get("invoiced_gp") is None:
        return None
    inv, ob = h["invoiced_gp"] / budget, (h.get("orderbook_gp") or 0) / budget
    return {"budget": budget, "invoiced": inv, "orderbook": ob, "total": inv + ob,
            "vs_py": _pct(gp.get("ytd"), gp.get("py"))}


def concentration(m: dict, top: int = 3) -> dict | None:
    """Share of CDS gross profit (YTD, I+OB) from the largest customers."""
    gps = sorted((c["iob_gp"] for c in m.get("customers", []) if c.get("iob_gp") is not None), reverse=True)
    total = sum(g for g in gps if g > 0)
    if not gps or total <= 0:
        return None
    return {"top": min(top, len(gps)), "share": sum(gps[:top]) / total, "largest": gps[0] / total,
            "customers": len(gps)}


def cash_outlook(m: dict, weeks: int = 13) -> dict | None:
    """The next ``weeks`` forward weeks of the cash schedule: bank cash low point and loan peak."""
    w = m.get("cash_summary", {}).get("weekly", {})
    labels, ends, rows = w.get("labels", []), w.get("week_ending", []), w.get("rows", {})
    # Index 0 is the catch-up bucket (activity to date); After has no week ending. Neither is a forward week.
    idx = [i for i, e in enumerate(ends) if i > 0 and e is not None][:weeks]
    bank, loans = rows.get("Bank Cash"), rows.get("Loans Outstanding")
    if not idx or not bank or not loans:
        return None
    low = min(idx, key=lambda i: bank[i])
    peak = max(idx, key=lambda i: loans[i])
    flows = ("Customer Payments (inflows)", "Supplier Purchases (outflows)", "New Loan Draws", "Loan Repayments")
    return {"weeks": len(idx), "index": idx, "first": labels[idx[0]], "last": labels[idx[-1]],
            "bank_low": bank[low], "bank_low_week": labels[low].split(" (")[0], "bank_low_date": ends[low],
            "loans_peak": loans[peak], "loans_peak_week": labels[peak].split(" (")[0],
            "totals": {f: sum(rows[f][i] for i in idx) for f in flows if f in rows}}


def history(reports: list[Report], key: str, upto: Report | None = None, n: int = 8) -> list[float]:
    """The last ``n`` values of a headline (or generic kpi) up to and including ``upto``, oldest first."""
    out = []
    for r in reports:
        h = r.metrics.get("headline") or {k["key"]: k["value"] for k in r.metrics.get("kpis", [])}
        if h.get(key) is not None:
            out.append(h[key])
        if upto is not None and r.period == upto.period:
            break
    return out[-n:]


def movers(m: dict, prev: dict | None = None, n: int = 2) -> list[dict]:
    """Customers with the largest absolute week-over-week GP change, largest first."""
    rows = [r for r in customer_rows(m, prev) if r["GP W/W"] is not None and abs(r["GP W/W"]) >= 0.5]
    return sorted(rows, key=lambda r: -abs(r["GP W/W"]))[:n]


def week_summary(m: dict, prev: dict | None = None) -> list[str]:
    """Plain-language notes on the week, built from the numbers only (no model involved)."""
    h, p = m.get("headline", {}), prior_headline(m, prev)
    notes = []
    gp, pgp = h.get("total_gp"), p.get("total_gp")
    if gp is not None:
        margin = f"margin {pct(h.get('gm_pct'))}"
        if h.get("gm_pct") is not None and p.get("gm_pct") is not None:
            margin += f" ({ppt(h['gm_pct'] - p['gm_pct'])})"
        if pgp:
            verb = "rose" if gp > pgp else ("fell" if gp < pgp else "was unchanged")
            amount = f" {money(abs(gp - pgp))}" if gp != pgp else ""
            notes.append(f"Gross profit YTD {verb}{amount} to {money(gp)} ({pct(gp / pgp - 1, signed=True)} on the "
                         f"week); {margin}.")
        else:
            notes.append(f"Gross profit YTD is {money(gp)}; {margin}. There is no prior week to compare with.")
    mv = movers(m, prev)
    if mv:
        notes.append("Largest customer moves: " + " and ".join(
            f"{r['Customer']} ({money(r['GP W/W'], signed=True)})" for r in mv) + ".")
    cov = budget_coverage(m)
    if cov:
        fy = f"FY{m['year'] % 100:02d}" if "year" in m else "full-year"
        s = (f"Invoiced GP covers {pct(cov['invoiced'], 0)} of the {fy} budget, and {pct(cov['total'], 0)} "
             "with the open orderbook")
        if cov.get("vs_py") is not None:
            s += f"; GP is {pct(abs(cov['vs_py']))} {'ahead of' if cov['vs_py'] >= 0 else 'behind'} prior year"
        notes.append(s + ".")
    cash, pcash = h.get("cash_incl_pharma"), p.get("cash_incl_pharma")
    if cash is not None:
        s = f"Group cash {money(cash)}"
        if pcash is not None:
            s += f" ({money(cash - pcash, signed=True)} on the week)"
        if h.get("net_debt_incl_pharma") is not None:
            s += f"; net debt {money(h['net_debt_incl_pharma'])}"
        notes.append(s + ".")
    out = cash_outlook(m)
    if out:
        notes.append(f"Over the next {out['weeks']} weeks the cash schedule has bank cash at its lowest at "
                     f"{money(out['bank_low'])} ({out['bank_low_week']}) and loans peaking at "
                     f"{money(out['loans_peak'])} ({out['loans_peak_week']}).")
    return notes


# --------------------------------------------------------------------------- figures in words (EUR thousands in)
def money(v: float | None, signed: bool = False) -> str:
    """EUR thousands -> '€36.6m' / '€950k'. ``signed`` adds '+' or '−'."""
    if v is None:
        return "–"
    sign = ("+" if v > 0 else "−" if v < 0 else "") if signed else ("−" if v < 0 else "")
    a = abs(v)
    return f"{sign}€{a / 1000:,.1f}m" if a >= 1000 else f"{sign}€{a:,.0f}k"


def pct(v: float | None, decimals: int = 1, signed: bool = False) -> str:
    if v is None:
        return "–"
    sign = ("+" if v > 0 else "−" if v < 0 else "") if signed else ("−" if v < 0 else "")
    return f"{sign}{abs(v) * 100:,.{decimals}f}%"


def ppt(v: float | None) -> str:
    """A change in a ratio, in percentage points."""
    if v is None:
        return "–"
    if abs(v) < 0.0005:
        return "unchanged"
    return f"{'+' if v > 0 else '−'}{abs(v) * 100:.1f} pt"


# --------------------------------------------------------------------------- the portfolio view
@dataclass
class PortfolioRow:
    key: str
    name: str
    cadence: str  # "Weekly" | "Monthly"
    latest: Report | None
    pending: int  # outputs waiting in the review queue
    revenue: float | None
    revenue_basis: str  # "Adj. revenue YTD" / "Revenue Aug 2026"
    profit: float | None
    profit_basis: str
    margin: float | None
    cash: float | None
    net_debt: float | None
    profit_change: float | None  # vs the prior period

    @property
    def status(self) -> str:
        if self.pending:
            return f"{self.pending} awaiting review"
        if self.latest is None:
            return "No reports yet"
        return "Published"


def portfolio_rows(companies: list[Company], reports: dict[str, list[Report]],
                   pending: dict[str, int]) -> list[PortfolioRow]:
    rows = []
    for c in companies:
        reps = reports.get(c.key, [])
        rep = reps[-1] if reps else None
        prev = reps[-2] if len(reps) > 1 else None
        m = rep.metrics if rep else {}
        if "headline" in m:
            h, p = m["headline"], prior_headline(m, prev.metrics if prev else None)
            rows.append(PortfolioRow(c.key, c.display_name, "Weekly", rep, pending.get(c.key, 0),
                                     h.get("adj_revenue"), "Adj. revenue YTD", h.get("total_gp"), "Gross profit YTD",
                                     h.get("gm_pct"), h.get("cash_incl_pharma"), h.get("net_debt_incl_pharma"),
                                     _diff(h.get("total_gp"), p.get("total_gp"))))
        else:
            k = {x["key"]: x.get("value") for x in m.get("kpis", [])}
            pk = {x["key"]: x.get("value") for x in (prev.metrics if prev else {}).get("kpis", [])}
            basis = m.get("period_label", "")
            rows.append(PortfolioRow(c.key, c.display_name, "Monthly" if basis else "Weekly", rep,
                                     pending.get(c.key, 0), k.get("revenue"), f"Revenue {basis}".strip() if rep else "",
                                     k.get("ebitda"), f"EBITDA {basis}".strip() if rep else "", k.get("ebitda_margin"),
                                     k.get("cash"), k.get("net_debt"), _diff(k.get("ebitda"), pk.get("ebitda"))))
    return rows


# --------------------------------------------------------------------------- portfolio monitoring: totals, signals, tracker
CASH_FLOOR_K = 2000.0       # projected bank cash below €2m in the next 13 weeks: watch
MARGIN_DROP = 0.005         # gross margin down 0.5 pt or more on the week
NET_DEBT_RISE = 0.10        # net debt up 10% or more on the week
BUDGET_PACE_GAP = 0.10      # invoiced GP more than 10 pt behind the share of the year gone
CONCENTRATION = 0.70        # top 3 customers above 70% of CDS gross profit
SIGNAL_RULES = ("Projected bank cash below €2m in the next 13 weeks (red when negative) · gross margin down "
                "0.5 pt or more · gross profit YTD lower than last week · net debt up 10% or more · invoiced "
                "gross profit more than 10 pt behind the share of the year gone · top 3 customers above 70% of "
                "CDS gross profit.")


@dataclass
class Signal:
    level: str  # "high" | "watch" | "info"
    title: str  # short: "Cash low point"
    text: str   # one sentence with the figures


def signals(m: dict, prev: dict | None = None) -> list[Signal]:
    """Rule-based flags from one weekly report, most serious first. Figures only; thresholds above."""
    h, p = m.get("headline", {}), prior_headline(m, prev)
    out: list[Signal] = []
    o = cash_outlook(m)
    if o and o["bank_low"] < 0:
        out.append(Signal("high", "Cash shortfall", f"Projected bank cash goes negative ({money(o['bank_low'])}) "
                                                    f"in {o['bank_low_week']}."))
    elif o and o["bank_low"] < CASH_FLOOR_K:
        out.append(Signal("watch", "Cash low point", f"Projected bank cash falls to {money(o['bank_low'])} in "
                                                     f"{o['bank_low_week']}."))
    gp, pgp = h.get("total_gp"), p.get("total_gp")
    if gp is not None and pgp is not None and gp < pgp - 0.5:
        out.append(Signal("watch", "Gross profit down", f"Gross profit YTD fell {money(pgp - gp)} on the week "
                                                        "(reversals or cancelled orders)."))
    gm, pgm = h.get("gm_pct"), p.get("gm_pct")
    if gm is not None and pgm is not None and gm - pgm <= -MARGIN_DROP:
        out.append(Signal("watch", "Margin down", f"Gross margin {pct(gm)}, {ppt(gm - pgm)} on the week."))
    nd, pnd = h.get("net_debt_incl_pharma"), p.get("net_debt_incl_pharma")
    if nd is not None and pnd and pnd > 0 and (nd - pnd) / pnd >= NET_DEBT_RISE:
        out.append(Signal("watch", "Net debt up", f"Net debt {money(nd)}, up {pct((nd - pnd) / pnd, 0)} on the "
                                                  "week."))
    cov = budget_coverage(m)
    if cov and m.get("cw"):
        gone = min(m["cw"] / 52, 1.0)
        if cov["invoiced"] < gone - BUDGET_PACE_GAP:
            out.append(Signal("watch", "Behind budget pace", f"Invoiced gross profit is {pct(cov['invoiced'], 0)} "
                                                             f"of the full-year budget with {pct(gone, 0)} of the "
                                                             "year gone."))
    c = concentration(m)
    if c and c["share"] > CONCENTRATION:
        out.append(Signal("info", "Customer concentration", f"Top {c['top']} customers are {pct(c['share'], 0)} "
                                                            "of CDS gross profit."))
    return out


def portfolio_totals(rows: list[PortfolioRow]) -> dict:
    """Sums over the weekly companies' latest reports (EUR k) and the prior values behind their changes."""
    weekly = [r for r in rows if r.cadence == "Weekly" and r.latest is not None]
    s = lambda f: sum(getattr(r, f) for r in weekly if getattr(r, f) is not None)  # noqa: E731
    return {"companies": len(weekly), "gp": s("profit"), "gp_change": s("profit_change"), "revenue": s("revenue"),
            "cash": s("cash"), "net_debt": s("net_debt")}


def latest_week(reports: dict[str, list[Report]], queue_items: list, today) -> tuple[int, int]:
    """The latest ISO week any company has reported (published or in the queue); else last calendar week."""
    seen = [(r.metrics["year"], r.metrics["cw"]) for reps in reports.values() for r in reps if "cw" in r.metrics]
    seen += [(i.year, i.cw) for i in queue_items]
    if seen:
        return max(seen)
    y, w, _ = (today - timedelta(days=7)).isocalendar()
    return (y, w)


def weeks_ending(last: tuple[int, int], n: int) -> list[tuple[int, int]]:
    """``n`` consecutive ISO weeks ending with ``last``, oldest first."""
    d = datetime.fromisocalendar(last[0], last[1], 5)
    out = []
    for _ in range(n):
        y, w, _ = d.isocalendar()
        out.append((y, w))
        d -= timedelta(days=7)
    return list(reversed(out))


TRACK_ORDER = ("published", "pending", "held", "rejected", "failed")  # for one week, the first that applies wins


def reporting_tracker(cfg: Config, companies: list[Company], reports: dict[str, list[Report]], queue_items: list,
                      weeks: list[tuple[int, int]]) -> dict[str, dict[tuple[int, int], str]]:
    """company key -> {(year, cw): published | pending | held | rejected | failed}; a missing week was not received."""
    grid: dict[str, dict] = {c.key: {} for c in companies}

    def put(key, wk, state):
        if key in grid and wk in weeks:
            cur = grid[key].get(wk)
            if cur is None or TRACK_ORDER.index(state) < TRACK_ORDER.index(cur):
                grid[key][wk] = state

    for c in companies:
        for r in reports.get(c.key, []):
            if "cw" in r.metrics:
                put(c.key, (r.metrics["year"], r.metrics["cw"]), "published")
        for e in run_log(cfg, c, limit=200):
            mt = re.search(r"CW(\d{2})[ _](\d{4})", f"{e.subject} {e.detail}")
            if mt and e.status in ("failed", "tamper", "error"):
                put(c.key, (int(mt.group(2)), int(mt.group(1))), "failed")
    for it in queue_items:
        if it.status in ("pending", "rejected"):
            put(it.company, (it.year, it.cw), it.status)
    for h in held_weeks(cfg):
        put(h.get("company"), (h.get("year"), h.get("cw")), "held")
    return grid


# --------------------------------------------------------------------------- source maps (ADR-0024)
MISSING_NAMES = {"weekly_gp": "weekly GP history", "cash_date": "cash snapshot date",
                 "opening_bank_cash": "opening bank cash", "budget": "full-year budgets", "cs": "Clinical Services segment",
                 "ea": "Early Access segment", "item": "medication column", "customer": "customer column",
                 "gp_pct": "margin column", "prior_col": "last week's balance sheet"}


def missing_inputs(m: dict) -> list[str]:
    """Optional inputs a company's map marks as not in its file, in words."""
    out = [k for k in ("cash_date", "opening_bank_cash", "weekly_gp") if k in m and m[k] is None]
    if (m.get("summary") or {}).get("budget_col", "x") is None:
        out.append("budget")
    out += [k for k, v in ((m.get("segments") or {}).get("rows") or {}).items() if v is None]
    out += [k for k, v in ((m.get("orderbook") or {}).get("headers") or {}).items() if v is None]
    if (m.get("balance_sheet") or {}).get("prior_col", "x") is None:
        out.append("prior_col")
    return [MISSING_NAMES.get(k, k) for k in out]


def map_location(m: dict, key: str) -> str:
    """Where a map puts one input, in words."""
    sheets, v = m.get("sheets") or {}, m.get(key)
    if isinstance(v, dict) and "cell" in v:
        return f"'{sheets.get(v.get('sheet'), v.get('sheet'))}'!{v['cell']}"
    if key == "orderbook":
        heads = [h for h in (v.get("headers") or {}).values() if h]
        return f"'{sheets.get('orderbook')}' header row {v.get('header_row')}: " + " | ".join(heads)
    if key == "summary":
        return (f"'{sheets.get('summary')}' labels in {v.get('label_col')}, values in {v.get('value_col')}: "
                + ", ".join(str(x) for x in (v.get("rows") or {}).values() if x))
    if key in ("segments", "balance_sheet", "customers"):
        seg = m.get("segments") or {}
        sheet = sheets.get(seg.get("sheet", "customer_level"))
        if key == "customers":
            return f"'{sheet}' from {v.get('header')!r} to {v.get('end')!r}"
        rows = ", ".join(str(x) for x in (v.get("rows") or {}).values() if x)
        return f"'{sheet}' column {seg.get('label_col')}: {rows}"
    if key == "weekly_gp":
        return f"'{sheets.get('weekly_gp')}' header row {v.get('header_row')}"
    return str(v)


def evidence_text(e) -> str:
    """Claude's evidence for one input, whatever shape it came in."""
    if e is None:
        return "–"
    if isinstance(e, str):
        return e
    if isinstance(e, dict):
        parts = [str(e[k]) for k in ("found", "text", "reason") if e.get(k)]
        samples = e.get("samples") or e.get("sample_values")
        if samples:
            parts.append("e.g. " + ", ".join(map(str, samples[:3])))
        return " · ".join(parts) or json.dumps(e)[:200]
    return str(e)[:200]
