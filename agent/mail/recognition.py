"""Decide whether an email carries a trading update, and for which company (ADR-0008).

Both must hold: the sender is on a company's allowlist, and an attachment name
matches that company's filename pattern. Anything else is ignored (and logged
by the caller) with no reply, so nobody can trigger a run by accident.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from agent.config import Company
from agent.mail.mailbox import Attachment, Email

CW_RE = re.compile(r"CW(\d{2})_(\d{4})", re.IGNORECASE)
# .xlsm is accepted, but its macros never run: recalculation force-disables them and the output
# is always a plain .xlsx (ADR-0017).
EXCEL_SUFFIXES = (".xlsx", ".xlsm")


@dataclass
class Match:
    company: Company
    attachment: Attachment
    cw: int
    year: int


@dataclass
class Verdict:
    matches: list[Match]
    reason: str  # why it was ignored, when matches is empty

    @property
    def accepted(self) -> bool:
        return bool(self.matches)


def recognise(mail: Email, companies: dict[str, Company]) -> Verdict:
    candidates = [c for c in companies.values() if c.pipeline and mail.sender in c.senders]
    xlsx = [a for a in mail.attachments if a.filename.lower().endswith(EXCEL_SUFFIXES)]
    if not candidates:
        hint = " (attachment name looks like a trading update)" if any(
            CW_RE.search(a.filename) for a in xlsx) else ""
        return Verdict([], f"sender {mail.sender or '<none>'} is not on any allowlist{hint}")
    if not xlsx:
        return Verdict([], "no .xlsx or .xlsm attachment")
    matches = []
    for a in xlsx:
        for c in candidates:
            m = CW_RE.search(a.filename)
            if c.matches_file(a.filename) and m:
                matches.append(Match(c, a, int(m.group(1)), int(m.group(2))))
                break
    if not matches:
        names = ", ".join(a.filename for a in xlsx)
        return Verdict([], f"no attachment matches the filename pattern ({names})")
    return Verdict(matches, "")
