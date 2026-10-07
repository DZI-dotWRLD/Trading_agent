"""VSCP portfolio dashboard (ADR-0011). Reads only metrics.json, state.json, heartbeat.json and the review queue
(ADR-0010).

    streamlit run dashboard/app.py        (or: .\\start-dashboard.ps1)

Three views: Portfolio (every company, what needs attention), Company (one company's week, read
like a board-pack page) and Review queue (approve or reject outputs, ADR-0017).
Config: config.yaml next to the repo root, or the path in VSCP_CONFIG.
"""
from __future__ import annotations

import os
import sys
from datetime import date
from html import escape as esc  # text from emails, workbooks, Claude or state.json is data, never markup
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent import config as config_mod  # noqa: E402
from agent.checks.validate import INSTRUCTIONS_CHECK  # noqa: E402
from agent.publishing.review import PENDING, ReviewError, ReviewQueue  # noqa: E402
from dashboard import data, ui  # noqa: E402
from dashboard.data import money, pct  # noqa: E402

st.set_page_config(page_title="VSCP Portfolio", page_icon="▪", layout="wide", initial_sidebar_state="collapsed")

PANEL_TITLES = {"overview": "Summary", "revenue_gp": "Revenue & margin", "customers": "Customers",
                "cash": "Cash & debt", "reports": "Files & audit"}
VIEWS = ("portfolio", "company", "review")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# --------------------------------------------------------------------------- data access
@st.cache_resource
def load_config(path: str) -> config_mod.Config:
    return config_mod.load(path)


@st.cache_data(ttl=30)
def reports_for(config_path: str, key: str) -> list[data.Report]:
    cfg = load_config(config_path)
    return data.load_reports(cfg, cfg.companies[key])


def html(s: str) -> None:
    st.html(s)


def nice_date(iso: str | None, weekday: bool = True) -> str:
    if not iso:
        return "–"
    d = date.fromisoformat(iso[:10])
    return f"{d:%a} {d.day} {d:%b %Y}" if weekday else f"{d.day} {d:%b %Y}"


# --------------------------------------------------------------------------- charts
def _style(chart: alt.Chart, height: int) -> alt.Chart:
    return (chart.properties(height=height, background="transparent")
            .configure_view(stroke=None)
            .configure_axis(labelFont="IBM Plex Sans", titleFont="IBM Plex Sans", labelColor=ui.INK_2,
                            titleColor=ui.INK_2, titleFontWeight="normal", labelFontSize=11, titleFontSize=11,
                            gridColor="#ebe8e1", domainColor=ui.RULE, tickColor=ui.RULE)
            .configure_legend(labelFont="IBM Plex Sans", labelColor=ui.INK_2, labelFontSize=12, symbolType="square"))


def gp_buildup_chart(m: dict) -> alt.Chart | None:
    hist = m.get("gp_history", [])
    if len(hist) < 2:
        return None
    wide = pd.DataFrame([{"CW": h["cw"], "Invoiced": h["invoiced"] / 1000, "Orderbook": h["orderbook"] / 1000,
                          "Total": h["total"] / 1000} for h in hist])
    long = wide.melt(id_vars=["CW"], value_vars=["Invoiced", "Orderbook"], var_name="Type", value_name="EUR m")
    x = alt.X("CW:Q", title="Calendar week", axis=alt.Axis(format="d", tickMinStep=1, grid=False),
              scale=alt.Scale(nice=False))
    area = (alt.Chart(long).mark_area(opacity=0.88, line={"strokeWidth": 2})
            .encode(x=x, y=alt.Y("EUR m:Q", stack="zero", title="€ millions"),
                    color=alt.Color("Type:N", scale=alt.Scale(domain=["Invoiced", "Orderbook"],
                                                              range=[ui.NAVY, ui.AMBER]),
                                    legend=alt.Legend(orient="top", title=None)),
                    order=alt.Order("Type:N", sort="ascending")))
    hover = alt.selection_point(nearest=True, on="pointerover", fields=["CW"], empty=False)
    rule = (alt.Chart(wide).mark_rule(color=ui.INK_3, strokeWidth=1)
            .encode(x="CW:Q", opacity=alt.condition(hover, alt.value(1), alt.value(0)),
                    tooltip=[alt.Tooltip("CW:Q", title="Week"), alt.Tooltip("Invoiced:Q", format=",.1f"),
                             alt.Tooltip("Orderbook:Q", format=",.1f"), alt.Tooltip("Total:Q", format=",.1f")])
            .add_params(hover))
    return _style(area + rule, 260)


def line_chart(df: pd.DataFrame, x: str, y: str, y_title: str, color: str = ui.NAVY, height: int = 200,
               x_type: str = "T") -> alt.Chart:
    hover = alt.selection_point(nearest=True, on="pointerover", fields=[x], empty=False)
    axis = alt.Axis(grid=False, labelAngle=0, **({"format": "%d %b"} if x_type == "T" else {}))
    enc_x = alt.X(f"{x}:{x_type}", title=None, axis=axis, sort=None)
    base = alt.Chart(df).encode(x=enc_x, y=alt.Y(f"{y}:Q", title=y_title, scale=alt.Scale(zero=False)))
    line = base.mark_line(strokeWidth=2, color=color)
    dots = base.mark_point(size=70, filled=True, color=color).encode(
        opacity=alt.condition(hover, alt.value(1), alt.value(0)),
        tooltip=[c for c in df.columns if c != x] + [alt.Tooltip(f"{x}:{x_type}", format="%d %b %Y")
                                                     if x_type == "T" else x]).add_params(hover)
    return _style(line + dots, height)


# --------------------------------------------------------------------------- portfolio view
def view_portfolio(cfg: config_mod.Config, pending: list, queue: ReviewQueue) -> None:
    companies = sorted(cfg.companies.values(), key=lambda c: (not c.pipeline, c.display_name))
    reports = {c.key: reports_for(st.session_state["config_path"], c.key) for c in companies}
    waiting: dict[str, int] = {}
    for item in pending:
        waiting[item.company] = waiting.get(item.company, 0) + 1
    today = date.today()
    rows = data.portfolio_rows(companies, reports, waiting)
    weekly = [c for c in companies if c.pipeline]
    all_items = queue.items()
    weeks = data.weeks_ending(data.latest_week(reports, all_items, today), 8)
    grid = data.reporting_tracker(cfg, weekly, reports, all_items, weeks)
    held = data.held_weeks(cfg)
    inbox = data.inbox_status(cfg)
    tot = data.portfolio_totals(rows)

    html(ui.masthead("Portfolio monitoring", "Portfolio overview",
                     f"{today:%A} {today.day} {today:%B %Y} &nbsp;·&nbsp; {len(rows)} companies "
                     "&nbsp;·&nbsp; € millions unless stated"))

    # -- headline cards
    this_wk = weeks[-1]
    received = sum(1 for c in weekly if grid[c.key].get(this_wk))
    problems = len(held) + sum(1 for c in weekly for st_ in grid[c.key].values() if st_ in ("failed", "rejected"))
    html(ui.kpis([
        ui.kpi(f"Reports for CW{this_wk[1]:02d}", f"{received} / {len(weekly)}",
               note="received, latest week" if received == len(weekly) else f"{len(weekly) - received} not yet in",
               kind="" if received == len(weekly) else "warn"),
        ui.kpi("Awaiting review", str(len(pending)),
               ui.link("Open the queue →", "go", view="review") if pending else '<span class="mute">queue empty</span>',
               kind="warn" if pending else ""),
        ui.kpi("On hold or failed", str(problems), note="in the last 8 weeks", kind="bad" if problems else ""),
        ui.kpi("Gross profit YTD", money(tot["gp"]), ui.delta(tot["gp_change"], money(tot["gp_change"], signed=True)),
               "on the week"),
        ui.kpi("Group cash", money(tot["cash"]),
               note=f"{tot['companies']} weekly compan{'y' if tot['companies'] == 1 else 'ies'}"),
        ui.kpi("Net debt", money(tot["net_debt"]), note="incl. Pharma Model"),
    ]))

    # -- what needs a person, and what the numbers flag
    left, right = st.columns([1, 1], gap="large")
    with left:
        html(ui.section("Needs attention"))
        items = []
        for it in pending:
            items.append(ui.attention(
                f"<span><b>{esc(it.display_name)}, CW{it.cw:02d} {it.year}</b> is waiting for review &nbsp;·&nbsp; "
                f"{it.checks_passed} of {it.checks_total} checks passed</span>" + ui.link("Review →", "go", view="review")))
        for h in held:
            name = cfg.companies[h["company"]].display_name if h["company"] in cfg.companies else h["company"]
            items.append(ui.attention(f"<span><b>{esc(name)}, CW{h['cw']:02d} {h['year']}</b> is on hold: "
                                      f"{esc(h['reason'])}. It runs by itself once that report is approved.</span>"))
        if inbox.get("failures"):
            items.append(ui.attention(f"<span><b>The inbox cannot be read</b> since "
                                      f"{esc(str(inbox.get('failing_since')))} ({inbox['failures']} attempts): "
                                      f"{esc(str(inbox.get('last_error')))}</span>", "late"))
        missing = [c.display_name for c in weekly if not grid[c.key].get(this_wk)
                   and not any(i.company == c.key for i in pending)]
        if missing:
            items.append(ui.attention(f"<span><b>No CW{this_wk[1]:02d} report yet</b> from {esc(', '.join(missing))}."
                                      "</span>", "calm"))
        html("".join(items) or ui.attention("<span>Nothing needs attention: the review queue is empty and the inbox "
                                            "is being read normally.</span>", "calm"))
    with right:
        html(ui.section("Watchlist"))
        order = {"high": 0, "watch": 1, "info": 2}
        flagged = []
        for c in weekly:
            reps = reports[c.key]
            if reps and "headline" in reps[-1].metrics:
                sigs = data.signals(reps[-1].metrics, reps[-2].metrics if len(reps) > 1 else None)
                if sigs:
                    flagged.append((min(order[x.level] for x in sigs), c, sigs, reps[-1].label))
        lines = [ui.watch_row(ui.link(c.display_name, view="company", company=c.key), label, sigs)
                 for _, c, sigs, label in sorted(flagged, key=lambda x: (x[0], x[1].display_name))]
        html("".join(lines) or '<div class="sig-none">No flags on the latest reports.</div>')
        html(f'<div class="small" style="margin-top:.4rem">Rules: {esc(data.SIGNAL_RULES)}</div>')

    # -- reporting tracker
    html(ui.section("Reporting tracker, the 8 weeks to the latest report"))
    html(ui.tracker([(ui.link(c.display_name, view="company", company=c.key), grid[c.key]) for c in weekly], weeks))

    # -- every company
    html(ui.section("Companies"))
    body = []
    for r in rows:
        kind = "wait" if r.pending else ("ok" if r.latest else "")
        latest = (f"{esc(r.latest.label)}<span class='basis'>{nice_date(r.latest.metrics['report_date'], False)}</span>"
                  if r.latest else '<span class="mute">–</span>')
        key = "total_gp" if r.cadence == "Weekly" and r.latest and "headline" in r.latest.metrics else "ebitda"
        body.append(("", [
            f"{ui.link(r.name, view='company', company=r.key)}<span class='basis'>{r.cadence} reporting</span>",
            latest, ui.status(r.status, kind),
            f"{ui.m1(r.revenue)}<span class='basis'>{esc(r.revenue_basis)}</span>",
            f"{ui.m1(r.profit)}<span class='basis'>{esc(r.profit_basis)}</span>",
            ui.chg(r.profit_change), ui.pc(r.margin), ui.m1(r.cash), ui.m1(r.net_debt),
            ui.spark(data.history(reports[r.key], key))]))
    html(ui.table(["Company", "Latest", "Status", "Revenue", "Profit", "Change", "Margin", "Cash", "Net debt",
                   "Profit trend"], body, scroll=True))
    html('<div class="small">Click a company to open its latest report. Change is against the previous report. '
         "Weekly companies show year-to-date figures (invoiced plus orderbook); monthly companies show the month.</div>")

    # -- budget: how much of the year is secured, company by company
    cov = [(r, data.budget_coverage(r.latest.metrics)) for r in rows if r.latest and "headline" in r.latest.metrics]
    cov = [(r, c) for r, c in cov if c]
    if cov:
        html(ui.section("Full-year gross profit budget secured"))
        scale = max([1.15] + [c["total"] + 0.05 for _, c in cov])
        gone = min(weeks[-1][1] / 52, 1.0)
        body = [("", [ui.link(r.name, view="company", company=r.key),
                      ui.coverage_bar(c["invoiced"], c["orderbook"], height=22, scale=scale, label=n == len(cov) - 1),
                      ui.pc(c["invoiced"], 0), ui.pc(c["total"], 0), ui.m1(c["budget"])]) for n, (r, c) in enumerate(cov)]
        html(ui.table(["Company", "Invoiced + open orderbook against budget", "Invoiced", "Secured", "Budget"], body))
        html(ui.legend([("Invoiced", ui.NAVY), ("Open orderbook", ui.AMBER)])
             + f'<div class="small">{pct(gone, 0)} of the year has gone. A company is on pace when its invoiced '
               "share is close to that.</div>")


# --------------------------------------------------------------------------- company view
def view_company(cfg: config_mod.Config, pending: list) -> None:
    keys = [c.key for c in sorted(cfg.companies.values(), key=lambda c: (not c.pipeline, c.display_name))]
    if st.session_state.get("company") not in keys:
        st.session_state["company"] = keys[0]
    left, mid, _ = st.columns([2, 2, 3])
    key = left.selectbox("Company", keys, key="company", format_func=lambda k: cfg.companies[k].display_name)
    company = cfg.companies[key]
    reports = reports_for(st.session_state["config_path"], key)
    if not reports:
        html(ui.masthead("Company", company.display_name))
        st.info(f"No reports yet. They appear under `{cfg.company_folder(key)}` after the first approved run.")
        return
    by_label = {r.label: r for r in reversed(reports)}
    if st.session_state.get(f"period_{key}") not in by_label:  # e.g. a link to a week that is not on file
        st.session_state.pop(f"period_{key}", None)
    weekly = "cw" in reports[-1].metrics
    rep = by_label[mid.selectbox(
        "Week" if weekly else "Period", list(by_label), key=f"period_{key}",
        format_func=lambda k: k + (f" (revision {by_label[k].metrics['revision']})"
                                   if by_label[k].metrics.get("revision", 1) > 1 else ""))]
    prev = data.previous(reports, rep)
    m = rep.metrics
    st.query_params.update({"view": "company", "company": key, "week": rep.label})

    meta = [f"Report date <b>{nice_date(m['report_date'])}</b>"]
    if m.get("cash_date"):
        meta.append(f"cash at {nice_date(m['cash_date'])}")
    src = m.get("prior", {})
    if weekly:
        meta.append("compared with " + ({"prior_report": "last week's report", "in_file_history":
                                         "the file's own history"}.get(src.get("source"), "no prior week")))
    meta.append("prepared by " + rep.built_by + (f", approved by {esc(str(m['approved_by']))}" if m.get("approved_by") else ""))
    waiting = [i for i in pending if i.company == key]
    if waiting:
        meta.append(f"<b>{len(waiting)} report{'s' if len(waiting) > 1 else ''} awaiting review</b>")
    title = f"{company.display_name}"
    kicker = (f"Weekly trading update · Week {m['cw']}, {m['year']}" if weekly
              else f"Monthly reporting · {m.get('period_label', '')}")
    html(ui.masthead(kicker, title, " &nbsp;·&nbsp; ".join(meta)))

    panels = [p for p in (company.panels or ["overview", "reports"]) if p in PAGES]
    for tab, p in zip(st.tabs([PANEL_TITLES[p] for p in panels]), panels):
        with tab:
            PAGES[p](cfg, company, reports, rep, prev)


def page_summary(cfg, company, reports, rep, prev) -> None:
    m, pm = rep.metrics, prev.metrics if prev else None
    if "headline" not in m:
        _generic_summary(reports, rep, prev)
        return
    h, p = m["headline"], data.prior_headline(m, pm)

    def card(label, key, fmt, adverse_if_negative=True, kind="m"):
        v, pv = h.get(key), p.get(key)
        d = None if v is None or pv is None else v - pv
        txt = (data.ppt(d) if kind == "pct" else money(d, signed=True)) if d is not None else "–"
        return ui.kpi(label, fmt(v), ui.delta(d, txt, adverse_if_negative), "on the week" if d is not None else "",
                      ui.spark(data.history(reports, key, rep), width=54, height=18))

    html(ui.kpis([card("Adj. revenue YTD", "adj_revenue", money), card("Gross profit YTD", "total_gp", money),
                  card("Gross margin", "gm_pct", pct, kind="pct"), card("Group cash", "cash_incl_pharma", money),
                  card("Net debt", "net_debt_incl_pharma", money, adverse_if_negative=False)]))
    left, right = st.columns([3, 2], gap="large")
    with left:
        html(ui.section("This week"))
        html(ui.note(data.week_summary(m, pm)))
    with right:
        html(ui.section("Flags"))
        sigs = data.signals(m, pm)
        html("".join(ui.signal(sg.level, sg.title, sg.text) for sg in sigs)
             or '<div class="sig-none">No flags on this report.</div>')

    prior_label = f"CW{m['cw'] - 1:02d}" if m["cw"] > 1 else "Prior week"
    html(ui.section("Key figures"))

    def row(label, key, cls="", kind="m", adverse_if_negative=True):
        v, pv = h.get(key), p.get(key)
        d = None if v is None or pv is None else v - pv
        if kind == "pct":
            cells = [ui.pc(v), ui.pc(pv), ui.chg(d, adverse_if_negative, "pt"), '<span class="mute">pt</span>']
        elif kind == "n":
            cells = [f"{v:,.0f}" if v is not None else "–", f"{pv:,.0f}" if pv is not None else "–",
                     ui.chg(d, adverse_if_negative, "n"), ui.pc_chg(None if not pv else d / pv, adverse_if_negative)]
        else:
            cells = [ui.m1(v), ui.m1(pv), ui.chg(d, adverse_if_negative),
                     ui.pc_chg(None if not pv or d is None else d / abs(pv), adverse_if_negative)]
        return (cls, [label, *cells, ui.spark(data.history(reports, key, rep))])

    rows = [("head", ["Profit and loss, year to date", "", "", "", "", ""]),
            row("Adjusted revenue", "adj_revenue"),
            row("Gross profit", "total_gp", "total"),
            row("of which invoiced", "invoiced_gp", "sub"),
            row("of which open orderbook", "orderbook_gp", "sub"),
            row("Gross margin", "gm_pct", kind="pct"),
            row("Gross profit as % of FY budget", "gp_budget_pct", kind="pct"),
            ("head", ["Cash and debt", "", "", "", "", ""]),
            row("Group cash (incl. Pharma Model)", "cash_incl_pharma"),
            row("Total debt", "total_debt", adverse_if_negative=False),
            row("Net debt (incl. Pharma Model)", "net_debt_incl_pharma", "total", adverse_if_negative=False),
            ("head", ["Orderbook (open CDS orders)", "", "", "", "", ""]),
            row("Open sales orders, value", "open_sales"),
            row("Open sales orders, number", "open_orders", kind="n"),
            row("Orderbook margin", "orderbook_margin_pct", kind="pct")]
    html(ui.table(["€ millions", f"CW{m['cw']:02d}", prior_label, "Change", "Change %", "Last 8 weeks"], rows))
    html('<div class="small">Year to date = invoiced plus open orderbook, as in the source Summary tab. Adjusted '
         "revenue excludes Early Access pass-through. Adverse changes are shown in red.</div>")

    cov = data.budget_coverage(m)
    if cov:
        html(ui.section(f"FY{m['year'] % 100:02d} gross profit budget: how much is secured"))
        c1, c2 = st.columns([3, 2])
        with c1:
            html(ui.coverage_bar(cov["invoiced"], cov["orderbook"]))
            html(ui.legend([(f"Invoiced {pct(cov['invoiced'], 0)}", ui.NAVY),
                            (f"Open orderbook {pct(cov['orderbook'], 0)}", ui.AMBER)]))
        with c2:
            html(ui.facts([(pct(cov["total"], 0), "of the full-year budget is invoiced or in the orderbook"),
                           (money(cov["budget"]), "full-year gross profit budget")]))

    chart = gp_buildup_chart(m)
    if chart is not None:
        html(ui.section("Gross profit build-up, year to date"))
        st.altair_chart(chart, width="stretch", theme=None)
        html('<div class="small">From the source file\'s Weekly GP tab. Hover for the figures of a week.</div>')


def _generic_summary(reports, rep, prev) -> None:
    kpis = data.generic_kpis(rep.metrics, prev.metrics if prev else None)
    keys = {x["label"]: x["key"] for x in rep.metrics.get("kpis", [])}
    cards = []
    for k in kpis:
        adverse = not any(w in k.label.lower() for w in ("debt", "cost"))
        fmt = pct if k.unit == "pct" else money
        txt = (data.ppt(k.change) if k.unit == "pct" else money(k.change, signed=True)) if k.change is not None else "–"
        cards.append(ui.kpi(k.label, fmt(k.value), ui.delta(k.change, txt, adverse),
                            f"vs {prev.label}" if prev and k.change is not None else "",
                            ui.spark(data.history(reports, keys[k.label], rep), width=54, height=18)
                            if k.label in keys else ""))
    html(ui.kpis(cards))
    if rep.metrics.get("note"):
        html(ui.section("This period"))
        html(ui.note([rep.metrics["note"]]))
    html(ui.section("Key figures"))
    rows = []
    for k in kpis:
        key = next((x["key"] for x in rep.metrics.get("kpis", []) if x["label"] == k.label), None)
        adverse = not any(w in k.label.lower() for w in ("debt", "cost"))
        if k.unit == "pct":
            cells = [ui.pc(k.value), ui.pc(k.prior), ui.chg(k.change, adverse, "pt"), '<span class="mute">pt</span>']
        else:
            cells = [ui.m1(k.value), ui.m1(k.prior), ui.chg(k.change, adverse),
                     ui.pc_chg(None if not k.prior or k.change is None else k.change / abs(k.prior), adverse)]
        rows.append(("", [k.label, *cells, ui.spark(data.history(reports, key, rep)) if key else ""]))
    prior_label = prev.label if prev else "Prior"
    html(ui.table(["€ millions", rep.label, prior_label, "Change", "Change %", "Trend"], rows))
    trend = pd.DataFrame(data.trend_rows(reports, data.generic_trend_keys(rep.metrics)))
    if len(reports) > 1 and not trend.empty:
        html(ui.section("Across periods"))
        metric = st.selectbox("Metric", list(dict.fromkeys(trend["Metric"])), key="generic_trend")
        d = trend[trend["Metric"] == metric].assign(**{"€ m": lambda t: t["Value"] / 1000})
        st.altair_chart(line_chart(d[["Week", "€ m"]], "Week", "€ m", "€ millions", x_type="N"), width="stretch",
                        theme=None)


def page_revenue(cfg, company, reports, rep, prev) -> None:
    m, pm = rep.metrics, prev.metrics if prev else None
    seg = data.segment_rows(m, pm)
    html(ui.section("By segment, year to date"))
    rows = []
    for r in seg:
        cls = "total" if r["Segment"] == "Total" else ""
        rows.append((cls, [r["Segment"], ui.m1(r["Adj. revenue YTD"]), ui.chg(r["Revenue W/W"]),
                           ui.pc_chg(r["Revenue vs PY"]), ui.pc(r["Revenue % of budget"], 0),
                           ui.m1(r["GP YTD"]), ui.chg(r["GP W/W"]), ui.pc_chg(r["GP vs PY"]),
                           ui.pc(r["GP % of budget"], 0), ui.pc(r["GP margin"])]))
    html(ui.table(["€ millions", "Adj. revenue", "Week", "vs PY", "% budget", "Gross profit", "Week", "vs PY",
                   "% budget", "Margin"], rows, scroll=True))
    html('<div class="small">Week = change since the previous report. vs PY = against the same point last year. '
         "% budget = against the full-year budget. Source: the Summary tab.</div>")

    html(ui.section("Gross profit against the full-year budget, by segment"))
    shares = [(s.get("inv_gp", 0) + s.get("ob_gp", 0)) / s["gp"]["budget"] for s in m.get("segments", {}).values()
              if isinstance(s, dict) and (s.get("gp") or {}).get("budget")]
    scale = max([1.15] + [x + 0.05 for x in shares])  # one scale, so the budget markers line up
    for key, name in data.SEGMENT_NAMES.items():
        s = m.get("segments", {}).get(key)
        budget = (s or {}).get("gp", {}).get("budget")
        if not s or not budget:
            continue
        inv, ob = s.get("inv_gp", 0) / budget, s.get("ob_gp", 0) / budget
        c1, c2 = st.columns([1, 3])
        c1.html(f'<div class="cov"><b style="color:{ui.INK}">{name}</b><br>{pct(inv + ob, 0)} secured · budget '
                f'{money(budget)}</div>')
        c2.html(ui.coverage_bar(inv, ob, height=22, scale=scale))
    html(ui.legend([("Invoiced", ui.NAVY), ("Open orderbook", ui.AMBER)]))

    trend = pd.DataFrame(data.trend_rows(reports, {"gm_pct": "Gross margin"}))
    if len(trend) > 1:
        html(ui.section("Gross margin across reports"))
        d = trend.assign(**{"Margin %": lambda t: (t["Value"] * 100).round(2)})[["Week", "Margin %"]]
        st.altair_chart(line_chart(d, "Week", "Margin %", "%", x_type="N", height=180), width="stretch", theme=None)


def page_customers(cfg, company, reports, rep, prev) -> None:
    m, pm = rep.metrics, prev.metrics if prev else None
    rows = data.customer_rows(m, pm)
    if not rows:
        st.info("No customer data in this report.")
        return
    conc = data.concentration(m)
    total = sum(r["GP YTD (I+OB)"] for r in rows if r["GP YTD (I+OB)"] > 0)
    if conc:
        html(ui.facts([(pct(conc["share"], 0), f"of CDS gross profit comes from the top {conc['top']} customers"),
                       (pct(conc["largest"], 0), f"from the largest, {rows[0]['Customer']}"),
                       (str(conc["customers"]), "customers listed on the Customer-Level tab")]))
    mv = data.movers(m, pm)
    if mv:
        html(ui.note(["Largest moves this week: " + " and ".join(
            f"{r['Customer']} ({money(r['GP W/W'], signed=True)})" for r in mv) + "."]))
    html(ui.section("Comparator Drug Sourcing customers, year to date"))
    body = [("", [esc(r["Customer"]), ui.m1(r["GP YTD (I+OB)"]),
                  f'{ui.share_bar(r["GP YTD (I+OB)"] / total if total else 0)} '
                  f'<span style="display:inline-block;width:2.6rem">{pct(r["GP YTD (I+OB)"] / total, 0) if total else "–"}'
                  "</span>",
                  ui.chg(r["GP W/W"]), ui.m1(r["Invoiced GP"]), ui.m1(r["Orderbook GP"]),
                  ui.m1(r["Revenue YTD (I+OB)"]), ui.pc(r["GP margin"])]) for r in rows]
    html(ui.table(["€ millions", "Gross profit", "Share of CDS GP", "Week", "Invoiced GP", "Orderbook GP",
                   "Revenue", "Margin"], body, scroll=True))
    html('<div class="small">Sorted by gross profit (invoiced plus orderbook). Week = change since the previous '
         "report; blank when there is no prior week for the customer.</div>")


def page_cash(cfg, company, reports, rep, prev) -> None:
    m = rep.metrics
    cash = m.get("cash", {})
    bs, bp = cash.get("balance_sheet", {}), cash.get("balance_sheet_prior", {})
    out = data.cash_outlook(m)
    d = lambda k: None if bs.get(k) is None or bp.get(k) is None else bs[k] - bp[k]  # noqa: E731
    items = [(money(bs.get("cash_incl_pharma")), f"group cash incl. Pharma Model ({money(d('cash_incl_pharma'), True)}"
                                                 " on the prior snapshot)"),
             (money(bs.get("net_debt_incl_pharma")), "net debt incl. Pharma Model")]
    if out:
        items += [(money(out["bank_low"]), f"lowest bank cash in the next {out['weeks']} weeks ({out['bank_low_week']})"),
                  (money(out["loans_peak"]), f"highest loans outstanding ({out['loans_peak_week']})")]
    html(ui.facts(items))
    html(f'<div class="small">Balance sheet at {nice_date(m.get("cash_date"))}. Outlook from the Cash Schedule tab: '
         "open sales orders as inflows, open purchase orders as outflows.</div>")

    w = m.get("cash_summary", {}).get("weekly", {})
    proj = pd.DataFrame([{"Week": lab.split(" (")[0], "Week ending": end,
                          "Bank cash, € m": round(w["rows"]["Bank Cash"][i] / 1000, 2),
                          "Loans, € m": round(w["rows"]["Loans Outstanding"][i] / 1000, 2)}
                         for i, (lab, end) in enumerate(zip(w.get("labels", []), w.get("week_ending", [])))
                         if end is not None and "Bank Cash" in w.get("rows", {})])
    if not proj.empty:
        html(ui.section("Projected balances, week by week"))
        c1, c2 = st.columns(2)
        with c1:
            html('<div class="cov"><b style="color:#1d2125">Bank cash</b></div>')
            st.altair_chart(line_chart(proj[["Week ending", "Week", "Bank cash, € m"]], "Week ending",
                                       "Bank cash, € m", "€ millions"), width="stretch", theme=None)
        with c2:
            html('<div class="cov"><b style="color:#1d2125">Loans outstanding</b></div>')
            st.altair_chart(line_chart(proj[["Week ending", "Week", "Loans, € m"]], "Week ending", "Loans, € m",
                                       "€ millions", color=ui.AMBER), width="stretch", theme=None)

    html(ui.section("Cash flow outlook"))
    basis = st.radio("Basis", ["weekly", "monthly"], horizontal=True, key="cash_basis",
                     format_func=lambda b: "Next 13 weeks" if b == "weekly" else "By month, full horizon",
                     label_visibility="collapsed")
    labels, rows = data.cash_summary_table(m, basis)
    if rows:
        idx = list(range(len(labels)))
        if basis == "weekly" and out:
            idx = [0] + out["index"]  # the catch-up bucket, then the next 13 weeks
        heads = [labels[i].split(" (")[0] if i else "To date" for i in idx]
        flows = [("", "Customer Payments (inflows)", "Customer receipts"),
                 ("", "Supplier Purchases (outflows)", "Supplier payments"),
                 ("total", "Net Operating Cash Flow", "Net operating cash flow"),
                 ("", "New Loan Draws", "Loan draws"), ("", "Loan Repayments", "Loan repayments"),
                 ("total", next((k for k in rows if k.startswith("Net ") and k.endswith("Cash Flow")
                                 and k != "Net Operating Cash Flow"), ""), "Net cash flow"),
                 ("head", None, "Balances at period end"),
                 ("", "Bank Cash", "Bank cash"), ("", "Loans Outstanding", "Loans outstanding"),
                 ("", "Invested (Project) Cash", "Invested project cash")]
        body = []
        for cls, key, label in flows:
            if key is None:
                body.append(("head", [label] + [""] * len(idx)))
            elif key in rows:
                body.append((cls, [label] + [ui.k0(rows[key][i]) for i in idx]))
        html(ui.table(["€ thousands", *heads], body, scroll=True))

    accounts = cash.get("accounts", [])
    if accounts:
        with st.expander(f"Cash by bank account ({len(accounts)} accounts)"):
            body = [("", [a["affiliate"], a["bank"], a.get("country") or "", ui.k0(a["eur_k"]),
                          ui.k0(a.get("prior_eur_k")),
                          ui.chg(None if a.get("prior_eur_k") is None else a["eur_k"] - a["prior_eur_k"], unit="k")])
                    for a in accounts]
            html(ui.table(["Affiliate", "Bank", "Country", "€ thousands", "Prior", "Change"], body))


def page_files(cfg, company, reports, rep, prev) -> None:
    html(ui.section(f"{rep.label}: files"))
    cols = st.columns(3)
    for col, key, title in ((cols[0], "output_file", "Download the output workbook"),
                            (cols[1], "source_file", "Download the source file")):
        p = rep.file(key)
        if p:
            col.download_button(title, p.read_bytes(), file_name=p.name, width="stretch", mime=XLSX,
                                key=f"dl_{key}_{rep.label}")
        elif rep.metrics.get(key):
            col.caption(f"{rep.metrics[key]} is not next to the metrics file.")
    cols[2].html(f'<div class="small">Folder<br><code>{esc(str(rep.path.parent))}</code></div>')

    html(ui.section("Every period on file"))
    html(ui.table(["Period", "Report date", "Revision", "Output", "Prepared by", "Prior week from"], [
        ("", [esc(r.label), nice_date(r.metrics["report_date"], False), str(r.metrics.get("revision", 1)),
              esc(str(r.metrics.get("output_file") or "–")), r.built_by,
              {"prior_report": "last week's report", "in_file_history": "own history", "none": "none"}.get(
                  (r.metrics.get("prior") or {}).get("source"), "–")]) for r in reversed(reports)]))

    log = data.run_log(cfg, company)
    html(ui.section("Processing log"))
    if not log:
        html('<div class="small">The service has not handled any emails for this company yet.</div>')
        return
    kind = {"published": "ok", "processed": "ok", "pending_review": "wait", "failed": "late", "tamper": "late"}
    html(ui.table(["Received", "Subject", "Status", "Detail", "Claude cost"], [
        ("", [esc(e.at.replace("T", " ")[:16]), esc(e.subject),
              ui.status(e.status.replace("_", " "), kind.get(e.status, "")), f'<span class="l">{esc(e.detail)}</span>', f"${e.cost_usd:.2f}" if e.cost_usd else "–"]) for e in log]))


PAGES = {"overview": page_summary, "revenue_gp": page_revenue, "customers": page_customers, "cash": page_cash,
         "reports": page_files}


# --------------------------------------------------------------------------- review queue
def view_review(cfg: config_mod.Config, queue: ReviewQueue, pending: list) -> None:
    """Outputs waiting for a decision (ADR-0017). Buttons only record the decision; the service publishes."""
    n = len(pending)
    html(ui.masthead("Review queue", f"{n} report{'s' if n != 1 else ''} waiting" if n else "Nothing is waiting",
                     "Every output is checked automatically, then waits here. Only an approved file is saved to "
                     "the shared drive, by the service, within about 10 seconds of the decision."))
    for item in pending:
        _review_item(queue, item)

    decided = [i for i in queue.items() if i.status != PENDING][:30]
    if decided:
        html(ui.section("Recent decisions"))
        kind = {"approved": "ok", "rejected": "wait", "publish_failed": "late"}
        html(ui.table(["Report", "Decision", "By", "When", "Note"], [
            ("", [esc(i.label), ui.status(i.status.replace("_", " "), kind.get(i.status, "")), esc(i.decided_by or "–"),
                  esc((i.decided_at or "").replace("T", " ")[:16]),
                  f'<span class="l">{esc(i.note or i.error or "")}</span>'])
            for i in decided]))


def _review_item(queue: ReviewQueue, item) -> None:
    m = item.metrics
    with st.container(border=True, key=f"rv_{item.id}"):
        _review_body(queue, item, m)


def _review_body(queue: ReviewQueue, item, m: dict) -> None:
    ok = item.checks_passed == item.checks_total
    flagged = any(str(w).startswith(INSTRUCTIONS_CHECK) for w in item.warnings)
    chips = [ui.status(f"{item.checks_passed} / {item.checks_total} checks passed", "ok" if ok else "wait"),
             ui.status("text addressed to an AI", "late") if flagged else "",
             f'<span class="small">received {esc(item.created_at.replace("T", " ")[:16])}'
             + (f" · Claude ${item.cost_usd:.2f}" if item.cost_usd else "") + "</span>"]
    html(f'<div class="rv-head"><div><div class="kicker">Weekly trading update'
         f'{f" · revision {item.revision}" if item.revision > 1 else ""}</div>'
         f'<h3>{esc(item.display_name)} · CW{item.cw:02d} {item.year}</h3></div>'
         f'<div class="rv-chips">{"".join(c for c in chips if c)}</div></div>')
    if (item.layout or {}).get("origin") == "discovered":
        _layout_card(item.layout)
    left, right = st.columns([3, 2], gap="large")
    with left:
        if m.get("headline"):
            html(ui.note(data.week_summary(m)))
            h, p = m["headline"], data.prior_headline(m)
            rows = [("", [lab, ui.m1(h.get(k)), ui.m1(p.get(k)), ui.chg(None if p.get(k) is None or h.get(k) is None
                                                                         else h[k] - p[k], adv)])
                    for lab, k, adv in (("Adjusted revenue YTD", "adj_revenue", True),
                                        ("Gross profit YTD", "total_gp", True),
                                        ("Group cash", "cash_incl_pharma", True),
                                        ("Net debt", "net_debt_incl_pharma", False))]
            html(ui.table(["€ millions", "This report", "Prior week", "Change"], rows))
    with right:
        if not ok:
            html('<div class="small">Some checks did not pass; they are listed below.</div>')
        for w in item.warnings:  # written by Claude, possibly echoing workbook text
            if str(w).startswith(INSTRUCTIONS_CHECK):
                html(ui.attention("<b>The company's file contains text addressed to an AI.</b> It may be an attempt to "
                                  "steer the automation. Check the figures in the output carefully before approving. "
                                  + esc(str(w)[len(INSTRUCTIONS_CHECK) + 2:]), "late"))
            else:
                html(ui.attention(esc(str(w))))
        if item.changed_elsewhere:
            html(ui.attention("Other files on the drive changed during the run (probably colleagues): "
                              + esc(", ".join(item.changed_elsewhere[:10])), "calm"))
        if item.output_path.exists():
            st.download_button("Download the output to check it", item.output_path.read_bytes(),
                               file_name=item.output_name, key=f"dl_{item.id}", width="stretch", mime=XLSX)
        if item.sources:
            with st.expander("Where the typed-in values came from"):
                html(ui.table(["Value", "Amount", "From"], [
                    ("", [esc(str(s.get("value", ""))), esc(str(s.get("amount", ""))),
                          f'<span class="l">{esc(str(s.get("from") or s.get("file") or ""))}</span>'])
                    for s in item.sources]))

        req = item.requested
        if req:
            html(ui.attention(f"Decision recorded: <b>{esc(str(req['decision']))}</b> by {esc(str(req['reviewer']))} at "
                              f"{esc(str(req['at']).replace('T', ' ')[:16])}. The service carries it out shortly; if this "
                              "stays, check that the service is running (<code>.\\start.ps1</code>).", "calm"))
            return
        with st.form(f"decide_{item.id}", border=False):
            who = st.text_input("Your name", value=st.session_state.get("reviewer", ""), key=f"who_{item.id}")
            note = st.text_input("Note (required to reject)", key=f"note_{item.id}")
            a, b = st.columns(2)
            approve = a.form_submit_button("Approve and publish", type="primary", width="stretch")
            reject = b.form_submit_button("Reject", width="stretch")
        if approve or reject:
            if not who.strip():
                st.error("Enter your name, so the decision is recorded against you.")
                return
            st.session_state["reviewer"] = who.strip()
            try:
                queue.request(item.id, "approve" if approve else "reject", who, note)
            except ReviewError as e:
                st.error(str(e))
                return
            st.rerun()


INPUT_NAMES = {"report_date": "Report date", "cash_date": "Cash snapshot date", "opening_bank_cash": "Opening bank cash",
               "orderbook": "Open orders table", "summary": "Revenue and GP totals", "segments": "P&L by segment",
               "customers": "CDS customers", "balance_sheet": "Balance sheet", "weekly_gp": "Weekly GP history"}


def _layout_card(layout: dict) -> None:
    """Claude mapped an unfamiliar workbook: show where it found each input, and what the file lacks (ADR-0024)."""
    m, ev = layout.get("map") or {}, layout.get("evidence") or {}
    missing = data.missing_inputs(m)
    html(ui.attention("<span><b>New file layout, mapped by Claude.</b> This company's workbook is laid out "
                      "differently from the template. Claude worked out where each input is, and code checked the "
                      "mapping against the file's own totals. Approving this report also approves the mapping for "
                      "the company's future files." + (f" <b>Not in this file:</b> {esc(', '.join(missing))}; those "
                                                       "rows show n/a." if missing else "") + "</span>", "calm"))
    with st.expander("Where Claude found each input"):
        html(ui.table(["Input", "Where", "What Claude saw"], [
            ("", [esc(INPUT_NAMES.get(k, k.replace("_", " "))), f'<span class="l">{esc(data.map_location(m, k))}</span>',
                  f'<span class="l">{esc(data.evidence_text(ev.get(k)))}</span>'])
            for k in INPUT_NAMES if m.get(k) is not None]))


# --------------------------------------------------------------------------- layout
def _apply_link(cfg: config_mod.Config) -> None:
    """Open the view a link asked for (?view=company&company=KEY&week=CW39 2026), once per page load."""
    if st.session_state.get("_link_applied"):
        return
    st.session_state["_link_applied"] = True
    qp = st.query_params
    if qp.get("view") in VIEWS:
        st.session_state["nav"] = qp["view"]
    if qp.get("company") in cfg.companies:
        st.session_state["company"] = qp["company"]
        if qp.get("week"):
            st.session_state[f"period_{qp['company']}"] = qp["week"]


@st.fragment(run_every=15)
def service_status(config_path: str) -> None:
    """The top bar's service line; refreshes by itself so a stopped service shows without a click."""
    cfg = load_config(config_path)
    st.html(ui.service_line(data.service_status(cfg), data.inbox_status(cfg), date.today()))


def main() -> None:
    html(ui.STYLE)
    config_path = os.environ.get("VSCP_CONFIG", str(ROOT / "config.yaml"))
    st.session_state["config_path"] = config_path
    try:
        cfg = load_config(config_path)
    except config_mod.ConfigError as e:
        st.error(f"Could not load the configuration: {e}")
        return
    queue = ReviewQueue(cfg.review_dir)
    pending = queue.items(PENDING)

    _apply_link(cfg)
    labels = {"portfolio": "Portfolio", "company": "Companies",
              "review": f"Review queue ({len(pending)})" if pending else "Review queue"}
    with st.container(key="topbar"):
        brand, nav, status, refresh = st.columns([2.2, 4, 3.6, 0.6], vertical_alignment="center")
        brand.html('<div class="brand">VSCP<span>Portfolio monitoring</span></div>')
        view = nav.radio("View", VIEWS, key="nav", horizontal=True, format_func=labels.get,
                         label_visibility="collapsed")
        with status:
            service_status(config_path)
        if refresh.button("↻", type="tertiary", help="Reload the figures (they also refresh every 30 seconds)"):
            st.cache_data.clear()
    st.query_params["view"] = view
    if view != "company":
        for k in ("company", "week"):
            st.query_params.pop(k, None)

    if view == "review":
        view_review(cfg, queue, pending)
    elif view == "company":
        view_company(cfg, pending)
    else:
        view_portfolio(cfg, pending, queue)


main()
