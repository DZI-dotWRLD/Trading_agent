"""Locate prior-week data for a report (ADR-0005).

Order: last week's source file in the company folder -> the current file's own
history -> nothing (values must then be reported as n/a, never invented).
Last week's _vClaude output carries the same numbers as its source (live links),
so the source file is the canonical place to read them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from agent.checks.metrics import customer_gp, headline, prior_from_history
from agent.workbook.reader import TradingUpdate

SOURCE_RE = re.compile(r"Trading_update_CW(\d{2})_(\d{4})(?:_r(\d+))?\.xls[xm]$", re.IGNORECASE)


@dataclass
class PriorWeek:
    source: str  # "prior_report" | "in_file_history" | "none"
    path: Path | None = None
    values: dict[str, float] = field(default_factory=dict)
    customers: dict[str, float] = field(default_factory=dict)
    report_date: object = None


def find_report(folder: Path, cw: int, year: int) -> Path | None:
    """Latest revision of the source file for (cw, year) in ``folder`` (non-recursive)."""
    best: tuple[int, Path] | None = None
    for p in folder.glob("*.xls[xm]"):
        m = SOURCE_RE.search(p.name)
        if m and int(m.group(1)) == cw and int(m.group(2)) == year:
            rev = int(m.group(3) or 1)
            if best is None or rev > best[0]:
                best = (rev, p)
    return best[1] if best else None


def previous_week(year: int, cw: int) -> tuple[int, int]:
    """The ISO (year, week) before (year, cw). Week 1 looks back to week 52 or 53 of the previous year."""
    y, w, _ = (date.fromisocalendar(year, cw, 1) - timedelta(weeks=1)).isocalendar()
    return y, w


def find_prior_report(reports_dir: Path, year: int, cw: int) -> Path | None:
    """Last week's source file for a report of (year, cw) saved in ``reports_dir``.

    In week 1 last week belongs to the previous year. With the default path template
    (``.../Trading Updates/{year}``) its file sits in the sibling folder for that year.
    """
    p_year, p_cw = previous_week(year, cw)
    folders = [reports_dir]
    if p_year != year and reports_dir.name == str(year):
        folders.append(reports_dir.with_name(str(p_year)))
    for folder in folders:
        if folder.is_dir() and (path := find_report(folder, p_cw, p_year)) is not None:
            return path
    return None


def prior_week(current: TradingUpdate, reports_dir: Path | None) -> PriorWeek:
    if reports_dir is not None:
        path = find_prior_report(reports_dir, *current.iso_week)
        if path is not None:
            tu = TradingUpdate(path, current.map)  # last week's file has this company's layout
            return PriorWeek("prior_report", path, headline(tu), customer_gp(tu), tu.report_date)
    hist = prior_from_history(current)
    if hist:
        return PriorWeek("in_file_history", current.path, hist, {})
    return PriorWeek("none")
