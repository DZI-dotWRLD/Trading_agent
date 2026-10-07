"""Give the generated tabs the sample output's look: fonts, fills, borders, alignment, number formats,
column widths, row heights, merged title rows and hidden gridlines.

Claude writes the content (values and formulas); this deterministic step dresses it. Styles are copied
from ``templates/vclaude_style.xlsx``, the provided sample's four tabs with every number and formula
removed (made by ``devtools/make_style_template.py``). Row and column counts change every week, so
each cell takes the style of the template cell with the same *role*:

- Cash Schedule: header rows 1-5 as they are; every project row like the template's first project row;
  totals-block row T+k like the template's T+k. Columns A-D as they are; daily column i like the
  template's day i (same model start date); spacers, the catch-up bucket, week i, After, Grand Total
  and Margin % like their template counterparts.
- Weekly and monthly summaries: rows as they are; columns by role (labels, catch-up, week or month i,
  After, Grand Total).
- Comparison tab: cell for cell (its layout is fixed).

Column grouping is copied on the summaries (the sample collapses the weekly catch-up column). It is not
copied on the Cash Schedule: the sample's hidden daily columns were hidden by hand for that one week (they
include days with cash movements), so repeating them by position would hide real activity.

Only the four generated tabs are touched; the source tabs stay byte-for-byte as received (ADR-0006).
Nothing here changes a value or a formula, so validation results are unaffected.
"""
from __future__ import annotations

import re
from copy import copy
from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

TEMPLATE = Path(__file__).parent / "templates" / "vclaude_style.xlsx"
SCHEDULE, WEEKLY, MONTHLY = "Cash Schedule", "Cash Summary (Weekly)", "Cash Summary (Monthly)"
WEEK_LABEL = re.compile(r"^CW\d{2} \d{4}$")
PROJECT_ROW = 6  # first project row on the Cash Schedule (the template's project rows all share one style)


class StyleError(Exception):
    pass


# --------------------------------------------------------------------------- structure of a tab
def _comparison_name(wb) -> str | None:
    return next((s for s in wb.sheetnames if re.fullmatch(r"CW\d{2} vs CW\d{2}", s)), None)


def _schedule_layout(ws: Worksheet) -> dict:
    """Where the parts of a Cash Schedule are, found from its labels (row 4 week labels, 'Total, Net')."""
    weeks = [c for c in range(1, ws.max_column + 1)
             if isinstance(ws.cell(4, c).value, str) and WEEK_LABEL.match(ws.cell(4, c).value.strip())]
    total = next((r for r in range(PROJECT_ROW, ws.max_row + 1) if ws.cell(r, 1).value == "Total, Net"), None)
    if not weeks or total is None:
        raise StyleError(f"{ws.title}: week labels in row 4 or the 'Total, Net' row not found")
    catchup = weeks[0] - 1
    return {"total": total, "weeks": weeks, "catchup": catchup, "spacers": [catchup - 2, catchup - 1],
            "grid_end": catchup - 3, "after": weeks[-1] + 1, "grand": weeks[-1] + 2, "margin": weeks[-1] + 3}


def _schedule_column_map(tgt: dict, src: dict) -> dict[int, int]:
    cols = {c: c for c in range(1, 5)}  # SO, Customer, Medication, Earliest PO date
    src_days = src["grid_end"] - 4
    for c in range(5, tgt["grid_end"] + 1):
        cols[c] = 5 + min(c - 5, src_days - 1)  # day i: the model start date is the same
    for t, s in zip(tgt["spacers"], src["spacers"]):
        cols[t] = s
    cols[tgt["catchup"]] = src["catchup"]
    for i, c in enumerate(tgt["weeks"]):
        cols[c] = src["weeks"][min(i, len(src["weeks"]) - 1)]
    for k in ("after", "grand", "margin"):
        cols[tgt[k]] = src[k]
    return cols


def _schedule_row_map(ws: Worksheet, tgt: dict, src: dict) -> dict[int, int]:
    rows = {r: r for r in range(1, PROJECT_ROW)}
    for r in range(PROJECT_ROW, tgt["total"]):
        rows[r] = PROJECT_ROW
    for k in range(0, ws.max_row - tgt["total"] + 1):
        rows[tgt["total"] + k] = src["total"] + k
    return rows


def _summary_column_map(tgt: Worksheet, src: Worksheet) -> dict[int, int]:
    """Column A, then the buckets by role: first (catch-up), middle ones by position, After, Grand Total."""
    def roles(ws):
        cols = [c for c in range(2, ws.max_column + 1) if ws.cell(4, c).value not in (None, "")]
        after = next(c for c in cols if str(ws.cell(4, c).value).strip() == "After")
        grand = next(c for c in cols if str(ws.cell(4, c).value).strip() == "Grand")
        return cols[0], [c for c in cols if cols[0] < c < after], after, grand
    t_first, t_mid, t_after, t_grand = roles(tgt)
    s_first, s_mid, s_after, s_grand = roles(src)
    cols = {1: 1, t_first: s_first, t_after: s_after, t_grand: s_grand}
    for i, c in enumerate(t_mid):
        cols[c] = s_mid[min(i, len(s_mid) - 1)]
    return cols


# --------------------------------------------------------------------------- copying
def _copy_cell_style(src, dst) -> None:
    dst.font, dst.fill, dst.border = copy(src.font), copy(src.fill), copy(src.border)
    dst.alignment, dst.protection = copy(src.alignment), copy(src.protection)
    if src.number_format != "General":
        dst.number_format = src.number_format


def _copy_sheet(src: Worksheet, dst: Worksheet, rows: dict[int, int], cols: dict[int, int],
                grouping: bool = False) -> None:
    # Each distinct template style is translated into the target workbook once, then reused: the Cash
    # Schedule has ~90,000 cells but only ~60 distinct styles.
    done: dict[tuple, object] = {}
    for r, sr in rows.items():
        for c, sc in cols.items():
            s, d = src.cell(sr, sc), dst.cell(r, c)
            key = (tuple(s._style) if s.has_style else None, d.number_format if s.number_format == "General" else None)
            if key in done:
                d._style = copy(done[key])
            else:
                _copy_cell_style(s, d)
                done[key] = d._style
        h = src.row_dimensions[sr].height
        if h:
            dst.row_dimensions[r].height = h
    widths, groups = column_widths(src), _column_groups(src) if grouping else {}
    for c, sc in cols.items():
        if sc in widths:
            dst.column_dimensions[get_column_letter(c)].width = widths[sc]
        if sc in groups:  # e.g. the weekly summary's catch-up column is grouped and collapsed in the sample
            dim = dst.column_dimensions[get_column_letter(c)]
            dim.outlineLevel, dim.hidden = groups[sc]
    _copy_sheet_settings(src, dst)


def column_widths(ws: Worksheet) -> dict[int, float]:
    """Explicitly set column widths by column number. Excel stores widths as ranges (min..max); reading
    ``ws.column_dimensions['D']`` for an unset column would invent openpyxl's default of 13 instead."""
    out = {}
    for dim in ws.column_dimensions.values():
        if dim.width and (dim.customWidth or dim.width != 13):
            for c in range(dim.min or 1, (dim.max or dim.min or 1) + 1):
                out[c] = dim.width
    return out


def _column_groups(ws: Worksheet) -> dict[int, tuple[int, bool]]:
    """Grouped (outlined) columns: column number -> (outline level, hidden)."""
    out = {}
    for dim in ws.column_dimensions.values():
        if dim.outlineLevel or dim.hidden:
            for c in range(dim.min or 1, (dim.max or dim.min or 1) + 1):
                out[c] = (dim.outlineLevel, bool(dim.hidden))
    return out


def _copy_sheet_settings(src: Worksheet, dst: Worksheet) -> None:
    """Gridlines, default sizes and the print setup (orientation, fit to page, margins)."""
    dst.sheet_view.showGridLines = src.sheet_view.showGridLines
    for k in ("defaultRowHeight", "customHeight", "defaultColWidth", "baseColWidth"):
        setattr(dst.sheet_format, k, getattr(src.sheet_format, k))
    for k in ("orientation", "fitToWidth", "fitToHeight", "scale", "paperSize"):
        setattr(dst.page_setup, k, getattr(src.page_setup, k))
    dst.page_margins = copy(src.page_margins)
    if src.sheet_properties.pageSetUpPr is not None:
        dst.sheet_properties.pageSetUpPr = copy(src.sheet_properties.pageSetUpPr)


def _copy_row_merges(src: Worksheet, dst: Worksheet, last_col: int) -> None:
    """Re-create the template's full-width merged rows (titles, section headers, notes) at this width."""
    for rng in list(dst.merged_cells.ranges):
        dst.unmerge_cells(str(rng))
    for rng in src.merged_cells.ranges:
        if rng.min_row == rng.max_row and rng.min_col == 1:
            dst.merge_cells(start_row=rng.min_row, start_column=1, end_row=rng.min_row, end_column=last_col)


def apply_sample_style(path: Path, template: Path = TEMPLATE) -> None:
    """Restyle the four generated tabs of the workbook at ``path`` in place, like the sample output."""
    src_wb = openpyxl.load_workbook(template)
    wb = openpyxl.load_workbook(path)
    missing = [s for s in (SCHEDULE, WEEKLY, MONTHLY) if s not in wb.sheetnames]
    cmp_dst, cmp_src = _comparison_name(wb), _comparison_name(src_wb)
    if missing or cmp_dst is None:
        raise StyleError(f"{path.name}: generated tabs missing: {missing or 'comparison tab'}")

    s_src, s_dst = src_wb[SCHEDULE], wb[SCHEDULE]
    t_lay, s_lay = _schedule_layout(s_dst), _schedule_layout(s_src)
    _copy_sheet(s_src, s_dst, _schedule_row_map(s_dst, t_lay, s_lay), _schedule_column_map(t_lay, s_lay))

    for name in (WEEKLY, MONTHLY):
        src, dst = src_wb[name], wb[name]
        cols = _summary_column_map(dst, src)
        _copy_sheet(src, dst, {r: r for r in range(1, src.max_row + 1)}, cols, grouping=True)
        _copy_row_merges(src, dst, max(cols))
        if src.print_area:
            dst.print_area = f"A1:{get_column_letter(max(cols))}{src.max_row}"

    src, dst = src_wb[cmp_src], wb[cmp_dst]
    _copy_sheet(src, dst, {r: r for r in range(1, src.max_row + 1)}, {c: c for c in range(1, src.max_column + 1)})
    if src.print_area:  # the comparison tab's layout is fixed, so its print area is too
        area = src.print_area[0] if isinstance(src.print_area, list) else src.print_area
        dst.print_area = area.split("!")[-1]
    wb.save(path)
