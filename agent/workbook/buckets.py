"""Cash Schedule time buckets, derived from the report date only.

Catch-up bucket: everything before the Monday that starts the ISO week after
the report date. Then ``forward_weeks`` ISO weeks (Mon-Sun), then "After".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta


@dataclass(frozen=True)
class Bucket:
    kind: str  # "catchup" | "week" | "after"
    label: str
    start: date | None  # inclusive; None = open
    end: date | None  # exclusive; None = open
    week_ending: date | None = None

    def contains(self, d: date | datetime | None) -> bool:
        if d is None:
            return False
        d = d.date() if isinstance(d, datetime) else d
        return (self.start is None or d >= self.start) and (self.end is None or d < self.end)


def _mdy(d: date) -> str:
    return f"{d.month}/{d.day}/{d.year % 100:02d}"


def catchup_cutoff(report_date: date) -> date:
    """Monday of the ISO week after the report date."""
    return report_date + timedelta(days=7 - report_date.weekday())


def build_buckets(report_date: date, forward_weeks: int = 28) -> list[Bucket]:
    cutoff = catchup_cutoff(report_date)
    _, cw, _ = report_date.isocalendar()
    # Labelled with the report date, as in the sample; it also holds the weekend up to the cutoff.
    buckets = [Bucket("catchup", f"CW{cw:02d} (through {_mdy(report_date)})", None, cutoff, report_date)]
    start = cutoff
    for _ in range(forward_weeks):
        end = start + timedelta(days=7)
        y, w, _ = start.isocalendar()
        buckets.append(Bucket("week", f"CW{w:02d} {y}", start, end, end - timedelta(days=1)))
        start = end
    last = buckets[-1]
    buckets.append(Bucket("after", f"After {last.label}", start, None))
    return buckets


def month_groups(buckets: list[Bucket]) -> list[tuple[str, list[int]]]:
    """Group week buckets into calendar months by week-ending date.

    Returns [(label, [bucket indexes])], with the catch-up and After buckets as
    their own groups at either end, matching the sample's monthly tab.
    """
    groups: list[tuple[str, list[int]]] = []
    for i, b in enumerate(buckets):
        if b.kind == "catchup":
            groups.append((f"Through {b.week_ending.day} {b.week_ending:%b}", [i]))
        elif b.kind == "after":
            groups.append(("After", [i]))
        else:
            label = f"{b.week_ending:%b %Y}"
            if groups and groups[-1][0] == label:
                groups[-1][1].append(i)
            else:
                groups.append((label, [i]))
    return groups
