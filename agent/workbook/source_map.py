"""Where a company's inputs live in its workbook: the source map (ADR-0024).

Every portfolio company reports the same kind of data (an open-orders table, P&L by segment, CDS customers,
a balance sheet, cash), but not necessarily in Inceptua's layout. A source map names, for one company's
workbook, where each input is: by sheet name, header text and row label, never by a cell found by guessing.

- ``INCEPTUA_MAP`` is the template's own layout and the default for every company.
- For an unfamiliar layout, Claude proposes a map (``agent.claude.discover``) with evidence; code checks it
  (``resolve`` here, then ``agent.workbook.map_check``); the reviewer approves it with the first report, and
  it is reused for that company from then on.

``resolve(wb, source_map)`` turns a map into concrete locations for one workbook (sheet, column letters, row
numbers). The reader, the validator and the build skill all use those resolved locations, so Claude's formulas
and the validator's own recomputation point at the same cells, found by code.

Map format (JSON). ``null`` marks an optional input the company's file doesn't have:

    {"schema": 1,
     "sheets": {"orderbook": ..., "summary": ..., "customer_level": ..., "cash": ..., "weekly_gp": ... | null},
     "report_date": {"sheet": "summary", "cell": "D2"},
     "cash_date": {"sheet": "cash", "cell": "C4"} | null,
     "opening_bank_cash": {"sheet": "cash", "cell": "I28"}
                        | {"sheet": "cash", "label": "Total ...", "label_col": "B", "value_col": "I"} | null,
     "orderbook": {"header_row": 7, "headers": {"so": "SalesOrderNumber", ..., "item": ... | null}},
     "summary": {"label_col": "C", "value_col": "F", "budget_col": "J" | null,
                 "rows": {"adj_revenue": "Total Adjusted Revenue**", "total_gp": "Total Gross Profit"}},
     "segments": {"sheet": "customer_level", "label_col": "C", "search_rows": [1, 40],
                  "columns": {"inv_rev": "D", "inv_gp": "E", "ob_rev": "G", "ob_gp": "H", "iob_rev": "I", "iob_gp": "J"},
                  "rows": {"cds": ..., "cs": ... | null, "ea": ... | null, "total": "Total"}},
     "customers": {"header": "...", "first_offset": 4, "end": "Total Comparator Drug Sourcing"},
     "balance_sheet": {"start": "Balance Sheet Summary", "current_col": "E", "prior_col": "H" | null,
                       "rows": {"cash": ..., "debt": ..., "net_debt": ..., "cash_incl_pharma": ...,
                                "net_debt_incl_pharma": ..., "holdco": "* Holdco" | null}},
     "weekly_gp": {"header_row": 123, "first_col": "E", "blocks": {"inv": 125, "ob": 134, "iob": 143}} | null,
     "insert_before": "DPCache_orderbook_Data" | null,
     "evidence": {...}}          # only in Claude's maps: what it saw at each location (shown to the reviewer)

A single-value input is either a fixed ``cell`` or, better, a ``label`` found in ``label_col`` with its value in
``value_col`` on the same row. Labels match case- and whitespace-insensitively. A label starting with ``*`` matches by suffix
(``"* Holdco"`` matches ``"Inceptua Holdco"``). Customers use the segment columns.
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl.utils import column_index_from_string, get_column_letter

SCHEMA = 1

# The fields every report needs. Without them the file can't be built; anything else may be null.
ORDERBOOK_REQUIRED = ("so", "sales", "purchase", "gp", "so_date", "po_date")
ORDERBOOK_OPTIONAL = ("customer", "item", "gp_pct")
SEGMENT_COLUMNS = ("inv_rev", "inv_gp", "ob_rev", "ob_gp", "iob_rev", "iob_gp")
SEGMENTS = ("cds", "cs", "ea", "total")
BALANCE_ROWS = ("cash", "debt", "net_debt", "cash_incl_pharma", "net_debt_incl_pharma", "holdco")

INCEPTUA_MAP: dict = {
    "schema": SCHEMA,
    "sheets": {"orderbook": "Orderbook CDS", "summary": "Summary", "customer_level": "Customer-Level",
               "cash": "Cash", "weekly_gp": "Weekly GP"},
    "report_date": {"sheet": "summary", "cell": "D2"},
    "cash_date": {"sheet": "cash", "cell": "C4"},
    # Total bank cash (it ties to the balance sheet's Cash). VSCP's sample output opens from Cash!I28, a single
    # account (Inceptua NL, about EUR 109k); corrected here, see docs/HOW_IT_WORKS.md, section 6.
    "opening_bank_cash": {"sheet": "cash", "label": "Total Cash at Operating Companies", "label_col": "B",
                          "value_col": "I"},
    "orderbook": {"header_row": 7, "headers": {
        "so": "SalesOrderNumber", "customer": "Customer Account Name", "item": "Item Name_",
        "sales": "Open Sales EUR", "purchase": "Open Puchase EUR",  # sic, as in the template
        "gp": "GP EUR", "gp_pct": "GP %",
        "so_date": "SO forecasted payment date", "po_date": "PO forecasted payment date"}},
    "summary": {"label_col": "C", "value_col": "F", "budget_col": "J",
                "rows": {"adj_revenue": "Total Adjusted Revenue**", "total_gp": "Total Gross Profit"}},
    "segments": {"sheet": "customer_level", "label_col": "C", "search_rows": [7, 15],
                 "columns": {"inv_rev": "D", "inv_gp": "E", "ob_rev": "G", "ob_gp": "H", "iob_rev": "I", "iob_gp": "J"},
                 "rows": {"cds": "Comparator Drug Sourcing", "cs": "Clinical Services (CS)",
                          "ea": "Early Access (EA)", "total": "Total"}},
    "customers": {"header": "Comparator Drug Sourcing Segment (Sorted by Invoiced Gross Profit)", "first_offset": 4,
                  "end": "Total Comparator Drug Sourcing"},
    "balance_sheet": {"start": "Balance Sheet Summary", "current_col": "E", "prior_col": "H",
                      "rows": {"cash": "Cash", "debt": "Debt", "net_debt": "Net Debt",
                               "cash_incl_pharma": "Cash incl. Pharma Model",
                               "net_debt_incl_pharma": "Net Debt incl. Pharma", "holdco": "* Holdco"}},
    "weekly_gp": {"header_row": 123, "first_col": "E", "blocks": {"inv": 125, "ob": 134, "iob": 143}},
    "insert_before": "DPCache_orderbook_Data",
}

# Inceptua's template spells one header both ways over time.
HEADER_ALIASES = {"open puchase eur": "open purchase eur"}


class MapError(Exception):
    """The map doesn't fit the workbook. ``problems`` lists every input that couldn't be found."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def norm(v) -> str:
    s = re.sub(r"\s+", " ", str(v)).strip().lower() if v is not None else ""
    return HEADER_ALIASES.get(s, s)


def _label_matches(cell_value, label: str) -> bool:
    if label.startswith("*"):
        return norm(cell_value).endswith(norm(label[1:]))
    return norm(cell_value) == norm(label)


def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(source_map: dict, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(source_map, indent=2, default=str), encoding="utf-8")


def default_map() -> dict:
    return copy.deepcopy(INCEPTUA_MAP)


# --------------------------------------------------------------------------- resolved locations
@dataclass
class Layout:
    """A map resolved against one workbook: concrete sheets, columns (letters) and rows. ``None`` = absent."""
    sheets: dict[str, str | None]
    report_date: tuple[str, str]                 # (sheet name, cell)
    cash_date: tuple[str, str] | None
    opening_bank_cash: tuple[str, str] | None
    ob_sheet: str
    ob_header_row: int
    ob_first_row: int
    ob_last_row: int
    ob_cols: dict[str, str | None]               # field -> column letter
    summary_sheet: str | None
    summary_value_col: str | None
    summary_budget_col: str | None
    summary_rows: dict[str, int | None]          # adj_revenue / total_gp -> row
    seg_sheet: str | None
    seg_cols: dict[str, str]                     # inv_rev ... iob_gp -> letter
    seg_rows: dict[str, int | None]              # cds / cs / ea / total -> row
    cust_label_col: str | None
    cust_first_row: int | None
    cust_end_row: int | None                     # the "Total ..." row (exclusive)
    bs_label_col: str | None
    bs_date_row: int | None                      # the row below the block's start: snapshot dates
    bs_current_col: str | None
    bs_prior_col: str | None
    bs_rows: dict[str, int | None]
    wgp_sheet: str | None
    wgp_header_row: int | None
    wgp_first_col: str | None
    wgp_blocks: dict[str, int] | None
    insert_before: str | None
    problems: list[str] = field(default_factory=list)  # optional inputs that were mapped but not found

    def col_index(self, field_: str) -> int | None:
        letter = self.ob_cols.get(field_)
        return column_index_from_string(letter) if letter else None

    def to_context(self) -> dict:
        """What the build skill gets in run_context.json: every input as a concrete location."""
        ob = {"sheet": self.ob_sheet, "header_row": self.ob_header_row, "first_row": self.ob_first_row,
              "last_row": self.ob_last_row, "columns": self.ob_cols}
        return {
            "sheets": self.sheets,
            "report_date": f"'{self.report_date[0]}'!{self.report_date[1]}",
            "cash_date": f"'{self.cash_date[0]}'!{self.cash_date[1]}" if self.cash_date else None,
            "opening_bank_cash": (f"'{self.opening_bank_cash[0]}'!{self.opening_bank_cash[1]}"
                                  if self.opening_bank_cash else None),
            "orderbook": ob,
            "summary": {"sheet": self.summary_sheet, "value_col": self.summary_value_col,
                        "budget_col": self.summary_budget_col, "rows": self.summary_rows},
            "segments": {"sheet": self.seg_sheet, "columns": self.seg_cols, "rows": self.seg_rows},
            "customers": {"sheet": self.seg_sheet, "label_col": self.cust_label_col,
                          "first_row": self.cust_first_row, "end_row": self.cust_end_row},
            "balance_sheet": {"sheet": self.seg_sheet, "label_col": self.bs_label_col, "date_row": self.bs_date_row,
                              "current_col": self.bs_current_col, "prior_col": self.bs_prior_col, "rows": self.bs_rows},
            "weekly_gp": ({"sheet": self.wgp_sheet, "header_row": self.wgp_header_row, "first_col": self.wgp_first_col,
                           "blocks": self.wgp_blocks} if self.wgp_sheet else None),
            "insert_before": self.insert_before,
        }


def _find_row(ws, col: str, label: str, start: int = 1, end: int | None = None) -> int | None:
    for r in range(max(start, 1), min(end or ws.max_row, ws.max_row) + 1):
        if _label_matches(ws[f"{col}{r}"].value, label):
            return r
    return None


def _cell_ref(wb, m: dict, sheets: dict, key: str, problems: list[str], required: bool) -> tuple[str, str] | None:
    spec = m.get(key)
    if not spec:
        if required:
            problems.append(f"{key}: not mapped")
        return None
    name = sheets.get(spec.get("sheet"))
    if not name:
        problems.append(f"{key}: sheet {spec.get('sheet')!r} is not mapped")
        return None
    if spec.get("label"):  # by its row label: survives rows added above it
        row = _find_row(wb[name], spec["label_col"], spec["label"])
        if row is None:
            problems.append(f"{key}: label {spec['label']!r} not found in {name!r} column {spec['label_col']}")
            return None
        return name, f"{str(spec['value_col']).upper()}{row}"
    return name, str(spec["cell"]).replace("$", "").upper()


def resolve(wb, source_map: dict | None = None) -> Layout:
    """Concrete locations of every input in ``wb`` (a workbook opened with data_only=True).

    Raises MapError listing everything required that can't be found. Optional inputs that are mapped but
    missing become ``None`` and are listed in ``Layout.problems``.
    """
    m = source_map or INCEPTUA_MAP
    problems: list[str] = []      # fatal
    soft: list[str] = []          # optional, missing
    names = set(wb.sheetnames)
    sheets: dict[str, str | None] = {}
    for key, name in (m.get("sheets") or {}).items():
        if name is None:
            sheets[key] = None
        elif name in names:
            sheets[key] = name
        else:
            (problems if key == "orderbook" else soft).append(f"sheet {name!r} ({key}) not in the workbook")
            sheets[key] = None

    report_date = _cell_ref(wb, m, sheets, "report_date", problems, required=True)
    cash_date = _cell_ref(wb, m, sheets, "cash_date", soft, required=False)
    opening_bank_cash = _cell_ref(wb, m, sheets, "opening_bank_cash", soft, required=False)

    # --- orderbook: header texts -> column letters, data rows to the last row with an SO
    ob = m.get("orderbook") or {}
    ob_sheet = sheets.get("orderbook")
    ob_cols: dict[str, str | None] = {f: None for f in ORDERBOOK_REQUIRED + ORDERBOOK_OPTIONAL}
    header_row, first_row, last_row = int(ob.get("header_row") or 0), 0, 0
    if ob_sheet and header_row:
        ws = wb[ob_sheet]
        found = {norm(ws.cell(header_row, c).value): c for c in range(ws.max_column, 0, -1)
                 if ws.cell(header_row, c).value not in (None, "")}
        for f, text in (ob.get("headers") or {}).items():
            if text is None:
                continue
            c = found.get(norm(text))
            if c is None:
                (problems if f in ORDERBOOK_REQUIRED else soft).append(
                    f"orderbook column {f}: header {text!r} not in {ob_sheet!r} row {header_row}")
            else:
                ob_cols[f] = get_column_letter(c)
        for f in ORDERBOOK_REQUIRED:
            if f not in (ob.get("headers") or {}) or (ob.get("headers") or {}).get(f) is None:
                problems.append(f"orderbook column {f}: not mapped")
        first_row = header_row + 1
        last_row = header_row
        if ob_cols["so"]:
            sc = column_index_from_string(ob_cols["so"])
            for r in range(first_row, ws.max_row + 1):
                if ws.cell(r, sc).value not in (None, ""):
                    last_row = r
        if last_row < first_row:
            problems.append(f"orderbook: no rows below the header in {ob_sheet!r}")
    else:
        problems.append("orderbook: sheet or header row not mapped")

    # --- Summary rows (revenue, GP, budgets): optional as a block
    sm = m.get("summary") or {}
    summary_sheet = sheets.get("summary")
    summary_rows = {"adj_revenue": None, "total_gp": None}
    if summary_sheet and sm:
        ws = wb[summary_sheet]
        for k, label in (sm.get("rows") or {}).items():
            if label is not None:
                summary_rows[k] = _find_row(ws, sm["label_col"], label, 1, 60)
                if summary_rows[k] is None:
                    soft.append(f"summary row {k}: label {label!r} not found in column {sm['label_col']}")

    # --- segments, customers and the balance sheet: one sheet ("customer_level" by default)
    sg = m.get("segments") or {}
    seg_sheet = sheets.get(sg.get("sheet", "customer_level"))
    seg_rows: dict[str, int | None] = {s: None for s in SEGMENTS}
    cust_first = cust_end = bs_date_row = None
    bs_rows: dict[str, int | None] = {k: None for k in BALANCE_ROWS}
    cs = m.get("customers") or {}
    bs = m.get("balance_sheet") or {}
    if seg_sheet:
        ws = wb[seg_sheet]
        lo, hi = (sg.get("search_rows") or [1, 60])
        for s, label in (sg.get("rows") or {}).items():
            if label is not None:
                seg_rows[s] = _find_row(ws, sg["label_col"], label, lo, hi)
                if seg_rows[s] is None:
                    (problems if s in ("cds", "total") else soft).append(
                        f"segment row {s}: label {label!r} not found in {seg_sheet!r} column {sg['label_col']}")
        if cs.get("header"):
            head = _find_row(ws, sg["label_col"], cs["header"])
            end = _find_row(ws, sg["label_col"], cs["end"], head or 1) if cs.get("end") else None
            if head is None or end is None:
                problems.append(f"customers: block {cs.get('header')!r} .. {cs.get('end')!r} not found in {seg_sheet!r}")
            else:
                cust_first, cust_end = head + int(cs.get("first_offset", 1)), end
        else:
            problems.append("customers: not mapped")
        if bs.get("start"):
            start = _find_row(ws, sg["label_col"], bs["start"])
            if start is None:
                problems.append(f"balance sheet: {bs['start']!r} not found in {seg_sheet!r}")
            else:
                bs_date_row = start + 1
                for k, label in (bs.get("rows") or {}).items():
                    if label is not None:
                        bs_rows[k] = _find_row(ws, sg["label_col"], label, start, start + 15)
                        if bs_rows[k] is None and k != "holdco":
                            (problems if k in ("cash", "debt", "net_debt") else soft).append(
                                f"balance sheet row {k}: label {label!r} not found")
        else:
            problems.append("balance sheet: not mapped")
    else:
        problems.append("segments: sheet not mapped")

    wg = m.get("weekly_gp")
    wgp_sheet = sheets.get("weekly_gp") if wg else None

    if problems:
        raise MapError(problems)
    return Layout(
        sheets=sheets, report_date=report_date, cash_date=cash_date, opening_bank_cash=opening_bank_cash,
        ob_sheet=ob_sheet, ob_header_row=header_row, ob_first_row=first_row, ob_last_row=last_row, ob_cols=ob_cols,
        summary_sheet=summary_sheet, summary_value_col=sm.get("value_col") if summary_sheet else None,
        summary_budget_col=sm.get("budget_col") if summary_sheet else None, summary_rows=summary_rows,
        seg_sheet=seg_sheet, seg_cols=dict(sg.get("columns") or {}), seg_rows=seg_rows,
        cust_label_col=sg.get("label_col"), cust_first_row=cust_first, cust_end_row=cust_end,
        bs_label_col=sg.get("label_col"), bs_date_row=bs_date_row,
        bs_current_col=bs.get("current_col"), bs_prior_col=bs.get("prior_col"), bs_rows=bs_rows,
        wgp_sheet=wgp_sheet, wgp_header_row=(wg or {}).get("header_row") if wgp_sheet else None,
        wgp_first_col=(wg or {}).get("first_col") if wgp_sheet else None,
        wgp_blocks=(wg or {}).get("blocks") if wgp_sheet else None,
        insert_before=m.get("insert_before") if m.get("insert_before") in names else None,
        problems=soft,
    )
