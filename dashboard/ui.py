"""Presentation pieces for the dashboard: page styles, statement tables, sparklines, coverage bars.

Everything here returns HTML strings, so it is testable without Streamlit. The look follows a
printed board pack rather than a web dashboard: serif headings, tabular figures, hairline
rules, negatives in parentheses, and one accent colour. Money comes in EUR thousands.
"""
from __future__ import annotations

import base64
from html import escape
from urllib.parse import urlencode

# Chart series (validated as a pair for colour-blind readers, both >= 3:1 on the paper colour).
NAVY, AMBER = "#2f62a8", "#c27a1e"
INK, INK_2, INK_3, RULE, PAPER, ADVERSE = "#1d2125", "#585e66", "#868c93", "#dcd8cf", "#faf9f6", "#a23b2a"

STYLE = f"""
<style>
:root {{
  --paper: {PAPER}; --panel: #f3f1ec; --ink: {INK}; --ink-2: {INK_2}; --ink-3: {INK_3};
  --rule: {RULE}; --navy: {NAVY}; --amber: {AMBER}; --adverse: {ADVERSE};
  --serif: "Source Serif 4", Georgia, "Times New Roman", serif;
  --sans: "IBM Plex Sans", "Segoe UI", Arial, sans-serif;
}}
header[data-testid="stHeader"] {{ background: transparent; }}
.block-container {{ padding-top: 1.2rem; max-width: 1240px; }}
h1, h2, h3 {{ font-family: var(--serif) !important; font-weight: 600 !important; letter-spacing: -0.01em; }}

.mast {{ padding: .6rem 0 .2rem; margin-bottom: .4rem; }}
.mast .kicker {{ font: 600 .72rem/1 var(--sans); letter-spacing: .12em; text-transform: uppercase; color: var(--ink-2); }}
.mast h1 {{ font-size: 2.05rem; line-height: 1.15; margin: .35rem 0 .25rem; padding: 0; color: var(--ink); }}
.mast .meta {{ font: .86rem/1.5 var(--sans); color: var(--ink-2); }}
.mast .meta b {{ color: var(--ink); font-weight: 600; }}

.section {{ font: 600 .74rem/1 var(--sans); letter-spacing: .1em; text-transform: uppercase; color: var(--ink-2);
            border-bottom: 1px solid var(--rule); padding: 1.6rem 0 .45rem; margin-bottom: .7rem; }}
.note {{ font: 1.02rem/1.6 var(--serif); color: var(--ink); max-width: 46rem; }}
.note p {{ margin: 0 0 .5rem; }}
.small {{ font: .8rem/1.45 var(--sans); color: var(--ink-3); }}

table.st {{ width: 100%; border-collapse: collapse; font: .88rem/1.35 var(--sans); color: var(--ink);
            font-variant-numeric: tabular-nums lining-nums; }}
table.st th {{ font-weight: 600; font-size: .72rem; letter-spacing: .04em; text-transform: uppercase; color: var(--ink-2);
               text-align: right; padding: .35rem .6rem; border-bottom: 1px solid var(--ink); white-space: nowrap; }}
table.st th:first-child, table.st td:first-child {{ text-align: left; padding-left: 0; }}
table.st td {{ text-align: right; padding: .42rem .6rem; border-bottom: 1px solid var(--rule); white-space: nowrap; }}
table.st td.l {{ text-align: left; white-space: normal; }}
table.st tr.sub td:first-child {{ padding-left: 1.1rem; color: var(--ink-2); }}
table.st tr.total td {{ border-top: 1px solid var(--ink); font-weight: 600; }}
table.st tr.head td {{ font-weight: 600; padding-top: .9rem; border-bottom: 1px solid var(--rule); }}
table.st .neg {{ color: var(--adverse); }}
table.st .mute {{ color: var(--ink-3); }}
table.st .basis {{ display: block; font-size: .72rem; color: var(--ink-3); }}
.scroll {{ overflow-x: auto; }}

.status {{ font: 500 .82rem/1.3 var(--sans); white-space: nowrap; }}
.status::before {{ content: ""; display: inline-block; width: .55rem; height: .55rem; margin-right: .4rem;
                   vertical-align: .05rem; background: var(--ink-3); }}
.status.wait::before {{ background: var(--amber); }}
.status.late::before {{ background: var(--adverse); }}
.status.ok::before {{ background: var(--navy); }}
.status.svc {{ font-size: .76rem; color: var(--ink-2); margin-top: .2rem; white-space: normal; }}
.status.svc b {{ color: var(--ink); font-weight: 600; }}

.facts {{ display: flex; flex-wrap: wrap; border-top: 1px solid var(--ink); border-bottom: 1px solid var(--rule);
          margin: .2rem 0 .4rem; }}
.facts > div {{ flex: 1 1 8rem; padding: .7rem 1rem .7rem 0; margin-right: 1rem; }}
.facts > div + div {{ border-left: 1px solid var(--rule); padding-left: 1rem; }}
.facts .v {{ font: 600 1.45rem/1.2 var(--serif); color: var(--ink); font-variant-numeric: tabular-nums lining-nums; }}
.facts .k {{ font: .78rem/1.35 var(--sans); color: var(--ink-2); margin-top: .2rem; }}

.attn {{ border-left: 3px solid var(--amber); background: #fff; border-top: 1px solid var(--rule);
         border-right: 1px solid var(--rule); border-bottom: 1px solid var(--rule); padding: .6rem .9rem; margin: .35rem 0;
         display: flex; justify-content: space-between; gap: 1rem; align-items: baseline;
         font: .9rem/1.45 var(--sans); color: var(--ink); }}
.attn.late {{ border-left-color: var(--adverse); }}
.attn.calm {{ border-left-color: var(--navy); }}

.cov {{ font: .8rem/1.3 var(--sans); color: var(--ink-2); }}
.cov .lbl {{ display: flex; justify-content: space-between; margin-bottom: .25rem; }}

div[data-testid="stTabs"] button p {{ font: 500 .92rem var(--sans); }}
/* Radio groups read as text tabs: no circles, the chosen one underlined. */
div[data-testid="stRadioGroup"] {{ gap: 1.6rem; }}
label[data-testid="stRadioOption"] > div > div:first-child:not([data-testid]) {{ display: none !important; }}
label[data-testid="stRadioOption"] {{ padding: .15rem 0; border-bottom: 2px solid transparent; cursor: pointer; }}
label[data-testid="stRadioOption"] p {{ color: var(--ink-2); }}
label[data-testid="stRadioOption"][data-selected="true"] {{ border-bottom-color: var(--ink); }}
label[data-testid="stRadioOption"][data-selected="true"] p {{ font-weight: 600; color: var(--ink); }}
div[data-testid="stExpander"] details {{ border-color: var(--rule); border-radius: 0; }}

/* ---- app bar ---- */
.st-key-topbar {{ border-bottom: 1px solid var(--rule); padding-bottom: .35rem; margin-bottom: .4rem; }}
.brand {{ font: 600 1.15rem/1.1 var(--serif); color: var(--ink); white-space: nowrap; }}
.brand span {{ font: 400 .8rem var(--sans); color: var(--ink-2); margin-left: .55rem; letter-spacing: .02em; }}
.pill {{ display: inline-flex; align-items: center; gap: .45rem; font: 500 .78rem/1.2 var(--sans); color: var(--ink-2);
         border: 1px solid var(--rule); background: #fff; padding: .32rem .7rem; border-radius: 999px; }}
.pill::before {{ content: ""; width: .5rem; height: .5rem; border-radius: 50%; background: var(--ink-3); flex: none; }}
.pill.ok::before {{ background: #2e7d4f; box-shadow: 0 0 0 3px rgba(46,125,79,.15); }}
.pill.wait::before {{ background: var(--amber); box-shadow: 0 0 0 3px rgba(194,122,30,.18); }}
.pill.late {{ color: var(--adverse); border-color: rgba(162,59,42,.35); background: #fbf1ee; }}
.pill.late::before {{ background: var(--adverse); }}
.pill b {{ color: var(--ink); font-weight: 600; }}
.pill.late b {{ color: var(--adverse); }}
.svc-wrap {{ display: flex; justify-content: flex-end; }}
.st-key-topbar button[kind="tertiary"] p {{ color: var(--ink-2); font-size: .8rem; }}

/* ---- headline cards ---- */
.kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(10.5rem, 1fr)); gap: .75rem; margin: .3rem 0 .6rem; }}
.kpi {{ background: #fff; border: 1px solid var(--rule); border-top: 3px solid var(--ink); padding: .75rem .9rem .7rem;
        display: flex; flex-direction: column; gap: .2rem; min-width: 0; }}
.kpi.warn {{ border-top-color: var(--amber); }}
.kpi.bad {{ border-top-color: var(--adverse); }}
.kpi .k {{ font: 600 .7rem/1.2 var(--sans); letter-spacing: .08em; text-transform: uppercase; color: var(--ink-2); }}
.kpi .v {{ font: 600 1.6rem/1.15 var(--serif); color: var(--ink); font-variant-numeric: tabular-nums lining-nums; }}
.kpi .top {{ display: flex; justify-content: space-between; align-items: center; gap: .5rem; min-height: 1.1rem; }}
.kpi .d {{ font: .8rem/1.3 var(--sans); color: var(--ink-2); }}
.kpi .d .neg {{ color: var(--adverse); }}
.kpi .d .pos {{ color: #2e7d4f; }}
.kpi a {{ color: inherit; }}

/* ---- watchlist ---- */
.sig {{ display: grid; grid-template-columns: 11rem 1fr; gap: .2rem .8rem; padding: .5rem 0 .5rem .8rem;
        border-left: 3px solid var(--ink-3); border-bottom: 1px solid var(--rule); font: .88rem/1.45 var(--sans); }}
.sig.high {{ border-left-color: var(--adverse); }}
.sig.watch {{ border-left-color: var(--amber); }}
.sig .t {{ font-weight: 600; color: var(--ink); }}
.sig .who {{ font-weight: 600; color: var(--ink); }}
.sig .basis {{ display: block; font: 400 .74rem var(--sans); color: var(--ink-3); margin-top: .1rem; }}
.sig .x {{ color: var(--ink-2); }}
.sig-none {{ font: .9rem/1.5 var(--sans); color: var(--ink-2); padding: .5rem 0 .5rem .8rem; border-left: 3px solid var(--navy); }}

/* ---- reporting tracker ---- */
table.trk {{ border-collapse: separate; border-spacing: 4px 5px; font: .82rem/1.2 var(--sans); color: var(--ink); }}
table.trk th {{ font: 600 .68rem/1 var(--sans); letter-spacing: .05em; color: var(--ink-2); text-align: center; padding: 0 0 .2rem; }}
table.trk th:first-child, table.trk td:first-child {{ text-align: left; padding-right: 1rem; white-space: nowrap; }}
table.trk td.c {{ width: 2.6rem; height: 1.15rem; border-radius: 2px; background: #fff; border: 1px dashed #cfcac0; }}
table.trk td.published {{ background: var(--navy); border: 1px solid var(--navy); }}
table.trk td.pending {{ background: var(--amber); border: 1px solid var(--amber); }}
table.trk td.held {{ background: repeating-linear-gradient(135deg, #f3e3cc 0 4px, #fff 4px 8px); border: 1px solid var(--amber); }}
table.trk td.rejected, table.trk td.failed {{ background: var(--adverse); border: 1px solid var(--adverse); }}
.key {{ display: inline-flex; align-items: center; gap: .35rem; margin-right: 1rem; font: .78rem var(--sans); color: var(--ink-2); }}
.key i {{ display: inline-block; width: 1.1rem; height: .7rem; border-radius: 2px; }}

/* ---- review cards ---- */
div[class*="st-key-rv_"] {{ background: #fff; border-color: var(--rule) !important; border-radius: 2px !important;
                           border-top: 3px solid var(--amber) !important; padding: .4rem .6rem .6rem; margin-bottom: 1rem; }}
.rv-head {{ display: flex; justify-content: space-between; align-items: flex-end; gap: 1rem; flex-wrap: wrap;
           border-bottom: 1px solid var(--rule); padding-bottom: .55rem; margin-bottom: .3rem; }}
.rv-head .kicker {{ font: 600 .7rem/1 var(--sans); letter-spacing: .1em; text-transform: uppercase; color: var(--ink-2); }}
.rv-head h3 {{ font-size: 1.45rem !important; margin: .3rem 0 0 !important; padding: 0 !important; color: var(--ink); }}
.rv-chips {{ display: flex; gap: 1rem; align-items: center; flex-wrap: wrap; }}

/* ---- links, tables ---- */
a.co {{ color: var(--ink); text-decoration: none; border-bottom: 1px solid var(--rule); }}
a.co:hover {{ color: var(--navy); border-bottom-color: var(--navy); }}
a.go {{ color: var(--navy); text-decoration: none; font-weight: 600; white-space: nowrap; }}
a.go:hover {{ text-decoration: underline; }}
table.st tbody tr:hover td {{ background: rgba(47,98,168,.04); }}
table.st td:has(> span.l) {{ white-space: normal; text-align: left; min-width: 12rem; }}
.kpi .top img {{ flex: none; }}
</style>
"""


# --------------------------------------------------------------------------- numbers for tables (EUR k in, €m shown)
def m1(v: float | None) -> str:
    """EUR thousands -> millions with one decimal, negatives in parentheses: '36.6', '(0.2)'."""
    if v is None:
        return '<span class="mute">–</span>'
    s = f"{abs(v) / 1000:,.1f}"
    return f"({s})" if v < -0.05 else s


def k0(v: float | None) -> str:
    """EUR thousands, no decimals, negatives in parentheses."""
    if v is None:
        return '<span class="mute">–</span>'
    s = f"{abs(v):,.0f}"
    return f"({s})" if v < -0.5 else s


def chg(v: float | None, adverse_if_negative: bool = True, unit: str = "m") -> str:
    """A change: '+1.5' or '(0.2)'; adverse moves in the adverse colour."""
    if v is None:
        return '<span class="mute">–</span>'
    if unit == "pt":
        if abs(v) < 0.0005:
            return '<span class="mute">0.0</span>'
        txt = f"{'+' if v > 0 else '−'}{abs(v) * 100:.1f}"
    elif unit == "k":
        if abs(v) < 0.5:
            return '<span class="mute">0</span>'
        txt = f"+{v:,.0f}" if v > 0 else f"({abs(v):,.0f})"
    elif unit == "n":
        if abs(v) < 0.5:
            return '<span class="mute">0</span>'
        txt = f"+{v:,.0f}" if v > 0 else f"({abs(v):,.0f})"
    else:
        if abs(v) < 50:
            return '<span class="mute">0.0</span>'
        txt = f"+{v / 1000:,.1f}" if v > 0 else f"({abs(v) / 1000:,.1f})"
    bad = (v < 0) == adverse_if_negative
    return f'<span class="neg">{txt}</span>' if bad else txt


def pc(v: float | None, decimals: int = 1) -> str:
    if v is None:
        return '<span class="mute">–</span>'
    return f"{v * 100:,.{decimals}f}%"


def pc_chg(v: float | None, adverse_if_negative: bool = True) -> str:
    if v is None:
        return '<span class="mute">–</span>'
    txt = f"{'+' if v >= 0 else '−'}{abs(v) * 100:.1f}%"
    return f'<span class="neg">{txt}</span>' if (v < 0) == adverse_if_negative and abs(v) >= 0.0005 else txt


def _img(svg: str, width: int | str, height: int, alt: str) -> str:
    """Inline SVG as an <img> data URI: Streamlit's HTML sanitiser drops <svg> but keeps images."""
    if 'xmlns=' not in svg:
        svg = svg.replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1)
    data = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    size = f'width="{width}" height="{height}"' if isinstance(width, int) else f'style="width:{width};height:auto"'
    return f'<img src="data:image/svg+xml;base64,{data}" {size} alt="{escape(alt)}" title="{escape(alt)}">'


# --------------------------------------------------------------------------- building blocks
def _clock(iso: str | None, today) -> str:
    if not iso:
        return "never"
    from datetime import datetime
    t = datetime.fromisoformat(iso)
    return f"{t:%H:%M}" if t.date() == today else f"{t.day} {t:%b} {t:%H:%M}"


def service_line(status: dict, inbox: dict, today) -> str:
    """The top bar's pill: is the service running, and when did it last check the inbox."""
    state = status.get("state", "unknown")
    if state == "running":
        cls, text = "ok", f"Service running · inbox checked <b>{_clock(status.get('last_poll'), today)}</b>"
    elif state == "busy":
        cls, text = "wait", f"Processing <b>{escape(str(status.get('busy')))}</b>"
    elif state == "stopped":
        cls, text = "late", f"Service stopped at {_clock(status.get('seen'), today)} · run <b>start-all.ps1</b>"
    elif state == "not_running":
        cls, text = "late", f"Service not running since {_clock(status.get('seen'), today)} · run <b>start-all.ps1</b>"
    else:
        cls, text = "", "Service has not run yet · run <b>start-all.ps1</b>"
    if inbox.get("failures") and state in ("running", "busy"):
        cls, text = "late", text + " · inbox unreachable"
    return f'<div class="svc-wrap"><span class="pill svc {cls}">{text}</span></div>'


def masthead(kicker: str, title: str, meta: str = "") -> str:
    return (f'<div class="mast"><div class="kicker">{escape(kicker)}</div><h1>{escape(title)}</h1>'
            + (f'<div class="meta">{meta}</div>' if meta else "") + "</div>")


def section(title: str) -> str:
    return f'<div class="section">{escape(title)}</div>'


def note(paragraphs: list[str]) -> str:
    return '<div class="note">' + "".join(f"<p>{escape(p)}</p>" for p in paragraphs) + "</div>"


def facts(items: list[tuple[str, str]]) -> str:
    """A strip of a few headline facts: [(value, label)]."""
    return '<div class="facts">' + "".join(
        f'<div><div class="v">{v}</div><div class="k">{escape(k)}</div></div>' for v, k in items) + "</div>"


def status(text: str, kind: str = "") -> str:
    return f'<span class="status {kind}">{escape(text)}</span>'


def attention(text: str, kind: str = "") -> str:
    return f'<div class="attn {kind}">{text}</div>'


def table(headers: list[str], rows: list[tuple[str, list[str]]], scroll: bool = False) -> str:
    """A statement table. ``rows`` = [(row class, cells)]; cells are ready HTML; the first is the label.

    Row classes: "" normal, "sub" indented, "total" ruled and bold, "head" a sub-heading row.
    """
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join(f'<tr class="{cls}">' + "".join(f"<td>{c}</td>" for c in cells) + "</tr>" for cls, cells in rows)
    html = f'<table class="st"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'
    return f'<div class="scroll">{html}</div>' if scroll else html


def spark(values: list[float], width: int = 84, height: int = 20) -> str:
    """A small line of the recent values; the last point is marked. Empty with fewer than two points."""
    if len(values) < 2:
        return '<span class="mute">–</span>'
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    step = (width - 4) / (len(values) - 1)
    pts = [(2 + i * step, height - 3 - (v - lo) / span * (height - 6)) for i, v in enumerate(values)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    x, y = pts[-1]
    svg = (f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
           f'<polyline points="{line}" fill="none" stroke="{NAVY}" stroke-width="1.6" stroke-linejoin="round"/>'
           f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" fill="{NAVY}"/></svg>')
    return _img(svg, width, height, f"Trend over the last {len(values)} reports")


def coverage_bar(invoiced: float, orderbook: float, width: int = 520, height: int = 30,
                 scale: float | None = None, label: bool = True) -> str:
    """Invoiced and orderbook as shares of a budget (1.0 = budget), with the budget marked.

    Pass the same ``scale`` to bars shown together, so their budget markers line up.
    """
    scale = scale or max(1.15, invoiced + orderbook + 0.05)
    x = lambda f: 2 + f / scale * (width - 4)  # noqa: E731
    inv_w, ob_w = x(invoiced) - 2, x(invoiced + orderbook) - x(invoiced)
    b = x(1.0)
    extra = 16 if label else 0
    return _img((f'<svg width="{width}" height="{height + extra}" viewBox="0 0 {width} {height + extra}">'
            f'<rect x="2" y="4" width="{inv_w:.1f}" height="{height - 8}" fill="{NAVY}" rx="2">'
            f'<title>Invoiced: {invoiced:.0%} of budget</title></rect>'
            f'<rect x="{x(invoiced) + 1:.1f}" y="4" width="{max(ob_w - 1, 0):.1f}" height="{height - 8}" '
            f'fill="{AMBER}" rx="2"><title>Open orderbook: {orderbook:.0%} of budget</title></rect>'
            f'<line x1="{b:.1f}" x2="{b:.1f}" y1="0" y2="{height}" stroke="{INK}" stroke-width="2"/>'
            + (f'<text x="{b:.1f}" y="{height + 12}" text-anchor="middle" font-size="11" fill="{INK_2}" '
               'font-family="IBM Plex Sans, Segoe UI, sans-serif">Budget</text>' if label else "") + '</svg>'),
                "100%", height + (16 if label else 0), f"Invoiced {invoiced:.0%} and open orderbook {orderbook:.0%} of budget")


def share_bar(share: float, width: int = 90) -> str:
    """A thin horizontal bar for a share in a table cell."""
    w = max(1.0, min(1.0, share) * width)
    return _img(f'<svg width="{width}" height="10" viewBox="0 0 {width} 10">'
                f'<rect x="0" y="2" width="{width}" height="6" fill="{RULE}"/>'
                f'<rect x="0" y="2" width="{w:.1f}" height="6" fill="{NAVY}"/></svg>', width, 10, f"{share:.0%}")


def legend(items: list[tuple[str, str]]) -> str:
    return '<div class="small">' + " &nbsp; ".join(
        f'<span style="display:inline-block;width:.7rem;height:.7rem;background:{c};vertical-align:-.05rem;'
        f'margin-right:.3rem"></span>{escape(t)}' for t, c in items) + "</div>"


# --------------------------------------------------------------------------- monitoring pieces
def link(text: str, cls: str = "co", **query: str) -> str:
    """A link to another view of this dashboard, in the same tab: link("Inceptua", view="company", company="Inceptua")."""
    q = urlencode(query)
    return f'<a class="{cls}" href="?{q}" target="_self">{escape(text)}</a>'


def kpi(label: str, value: str, delta_html: str = "", note: str = "", spark_html: str = "", kind: str = "") -> str:
    """One headline card: label, value, and a footer with the change (ready HTML) and an optional sparkline."""
    return (f'<div class="kpi {kind}"><div class="top"><span class="k">{escape(label)}</span>{spark_html}</div>'
            f'<div class="v">{value}</div><div class="d">{delta_html}{" " + escape(note) if note else ""}</div></div>')


def kpis(cards: list[str]) -> str:
    return '<div class="kpis">' + "".join(cards) + "</div>"


def delta(v: float | None, text: str, adverse_if_negative: bool = True) -> str:
    """A change for a card: red when adverse, green when favourable, plain when flat, a dash when unknown."""
    if v is None or text in ("–", ""):
        return '<span class="mute">–</span>'
    if abs(v) < 1e-9 or text == "unchanged":
        return f"<span>{escape(text)}</span>"
    good = (v > 0) == adverse_if_negative
    return f'<span class="{"pos" if good else "neg"}">{escape(text)}</span>'


def signal(level: str, title: str, text: str, who: str = "") -> str:
    """One watchlist line. ``who`` (ready HTML, e.g. a link) names the company on the portfolio page."""
    if who:
        return (f'<div class="sig {level}"><span class="who">{who}</span><span><span class="t">{escape(title)}</span>'
                f' &nbsp;<span class="x">{escape(text)}</span></span></div>')
    return f'<div class="sig {level}"><span class="t">{escape(title)}</span><span class="x">{escape(text)}</span></div>'


def watch_row(who: str, label: str, sigs: list) -> str:
    """One company's flags on the portfolio watchlist; the border shows the most serious."""
    level = next((lv for lv in ("high", "watch", "info") if any(x.level == lv for x in sigs)), "info")
    items = "".join(f'<div><span class="t">{escape(x.title)}.</span> <span class="x">{escape(x.text)}</span></div>'
                    for x in sigs)
    return f'<div class="sig {level}"><span class="who">{who}<span class="basis">{escape(label)}</span></span><span>{items}</span></div>'


TRACK_LABELS = {"published": "Published", "pending": "Awaiting review", "held": "On hold",
                "rejected": "Rejected", "failed": "Failed", None: "Not received"}


def tracker(rows: list[tuple[str, dict]], weeks: list[tuple[int, int]]) -> str:
    """Companies x weeks, one square per week: [(company cell html, {(year, cw): state})]."""
    head = "<th></th>" + "".join(f"<th>CW{w:02d}</th>" for _, w in weeks)
    body = ""
    for name, states in rows:
        cells = "".join(
            f'<td class="c {states.get(wk) or ""}" title="CW{wk[1]:02d} {wk[0]}: {TRACK_LABELS[states.get(wk)]}"></td>'
            for wk in weeks)
        body += f"<tr><td>{name}</td>{cells}</tr>"
    keys = (("Published", f"background:{NAVY}"), ("Awaiting review", f"background:{AMBER}"),
            ("On hold", f"background:repeating-linear-gradient(135deg,#f3e3cc 0 3px,#fff 3px 6px);border:1px solid {AMBER}"),
            ("Failed or rejected", f"background:{ADVERSE}"), ("Not received", "border:1px dashed #cfcac0"))
    key = "".join(f'<span class="key"><i style="{st}"></i>{t}</span>' for t, st in keys)
    return (f'<div class="scroll"><table class="trk"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'
            f'<div style="margin-top:.4rem">{key}</div>')
