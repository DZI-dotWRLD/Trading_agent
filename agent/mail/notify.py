"""Emails to the VSCP team (ADR-0007, ADR-0017): review needed, approved, rejected, run failed, week on hold,
inbox unreachable.

Plain text only, and only ever to the configured VSCP recipients, never back to the sender.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agent.checks.validate import INSTRUCTIONS_CHECK

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024  # Gmail's limit is 25 MB including encoding overhead
SIGNATURE = "VSCP Trading-Update Agent"


@dataclass
class Message:
    subject: str
    text: str
    html: str | None = None
    attachments: list[Path] = field(default_factory=list)


def review_needed(item, dashboard_url: str | None = None) -> Message:
    """A validated output is waiting in the review queue. Nothing is on the drive yet (ADR-0017)."""
    revised = item.revision > 1
    subject = f"Review needed: {item.label}" + (" (revised)" if revised else "")
    attach = item.output_path.exists() and item.output_path.stat().st_size <= MAX_ATTACHMENT_BYTES
    lines = ["Hi team,", "",
             f"The updated report for {item.display_name} CW{item.cw:02d} {item.year} is ready for your review"
             + (" (it follows an earlier file for the same week)" if revised else "") + ".",
             f"It passed {item.checks_passed} of {item.checks_total} automatic checks.",
             "It will be saved to the shared drive only after someone approves it.", ""]
    lines.append(f"The file is attached for review: {item.output_name}" if attach
                 else f"The file is too large to attach: {item.output_name}")
    if dashboard_url:
        lines.append(f"Approve or reject it in the dashboard: {dashboard_url.rstrip('/')}/?view=review")
    else:
        lines.append(f'Approve or reject it with: python -m agent review approve {item.id}')
    if (item.layout or {}).get("origin") == "discovered":
        lines += ["", "New file layout: this company's workbook is laid out differently from the template. Claude "
                  "mapped where each input is, and code checked the mapping. The mapping is shown on the review "
                  "page; approving this report also approves it for this company's future files."]
    if any(str(w).startswith(INSTRUCTIONS_CHECK) for w in item.warnings):
        lines += ["", "WARNING: the company's file contains text addressed to an AI (see below). It may be an attempt "
                  "to steer the automation. Check the figures carefully before approving."]
    if item.warnings:
        lines += ["", "Warnings for the reviewer:"] + [f"  - {w}" for w in item.warnings[:10]]
    if item.changed_elsewhere:
        lines += ["", "Note: other files on the shared drive changed while this run was in progress "
                  f"(probably colleagues): {', '.join(item.changed_elsewhere[:10])}"]
    lines += ["", SIGNATURE]
    return Message(subject, "\n".join(lines), attachments=[item.output_path] if attach else [])


def report_published(item, dashboard_url: str | None = None) -> Message:
    subject = f"Approved and saved: {item.label}"
    lines = ["Hi team,", "",
             f"{item.decided_by} approved the updated report for {item.display_name} CW{item.cw:02d} {item.year}.",
             f"It is saved on the shared drive: {item.published}"]
    if item.note:
        lines.append(f"Reviewer's note: {item.note}")
    if dashboard_url:
        lines.append(f"Dashboard: {dashboard_url}")
    lines += ["", SIGNATURE]
    return Message(subject, "\n".join(lines))


def report_rejected(item) -> Message:
    subject = f"Rejected, not saved: {item.label}"
    lines = ["Hi team,", "",
             f"{item.decided_by} rejected the updated report for {item.display_name} CW{item.cw:02d} {item.year}. "
             "Nothing was written to the shared drive.", "", f"Reason: {item.note}", "",
             f"The company's file is saved at: {item.source}",
             "To build it again (for example after the skill or the file is fixed), run:",
             f'  python -m agent process "{item.source}" --company "{item.company}"', "", SIGNATURE]
    return Message(subject, "\n".join(lines))


def publish_failed(item) -> Message:
    subject = f"ACTION NEEDED: {item.label} was approved but could not be saved"
    lines = ["Hi team,", "", f"{item.decided_by} approved {item.output_name}, but it was not saved to the drive.",
             "", f"Reason: {item.error}", "", f"The reviewed file is kept at: {item.output_path}", "", SIGNATURE]
    return Message(subject, "\n".join(lines))


def run_failed(display_name: str, cw: int | None, year: int | None, source: Path | None, reason: str,
               details: list[str], log_dir: Path | None, company_key: str | None = None) -> Message:
    week = f" CW{cw:02d} {year}" if cw else ""
    subject = f"ACTION NEEDED: {display_name}{week} report was not produced"
    lines = ["Hi team,", "",
             f"The updated report for {display_name}{week} could not be produced. "
             "Nothing was written to the shared drive.", "", f"Reason: {reason}"]
    if details:
        lines += ["", "Details:"] + [f"  - {d}" for d in details[:15]]
    if source:
        lines += ["", f"The file received from the company is saved at: {source}"]
    if log_dir:
        lines.append(f"Run logs: {log_dir}")
    if source:
        lines += ["", "To retry after fixing the cause, run:",
                  f'  python -m agent process "{source}" --company "{company_key or display_name}"']
    lines += ["", SIGNATURE]
    return Message(subject, "\n".join(lines))


def week_on_hold(display_name: str, cw: int, year: int, reason: str) -> Message:
    """A week arrived before last week's report was published; it runs by itself once that is done."""
    s = f"On hold: {display_name} CW{cw:02d} {year} is waiting for last week's report"
    lines = ["Hi team,", "", f"The file for {display_name} CW{cw:02d} {year} has been received and saved.",
             f"It is on hold: {reason}.",
             "Its opening loan balance is carried forward from last week's published report, so it cannot be "
             "built before that report exists.", "",
             "It will be processed automatically as soon as last week's report is approved (or a corrected file "
             "for last week is sent and approved). Nothing else needs to be done.", "", SIGNATURE]
    return Message(s, "\n".join(lines))


def inbox_unreachable(mailbox: str, since: str, failures: int, error: str) -> Message:
    subject = f"ACTION NEEDED: the agent cannot read the inbox {mailbox}"
    text = (f"Hi team,\n\nThe agent has not been able to read {mailbox} since {since} ({failures} attempts in a row), "
            "so no new weekly files are being picked up.\n\n"
            f"Last error: {error}\n\n"
            "Common causes: the mailbox password or app password changed or was revoked, IMAP access was turned off, "
            "or the PC is offline. Check with:\n  python -m agent check\n\n"
            "The agent keeps trying and will email again once the inbox can be read.\n\n"
            f"{SIGNATURE}")
    return Message(subject, text)


def inbox_recovered(mailbox: str, since: str) -> Message:
    subject = f"Inbox readable again: {mailbox}"
    text = (f"Hi team,\n\nThe agent can read {mailbox} again (it could not since {since}). "
            "Any weekly files that arrived in the meantime are being processed now.\n\n"
            f"{SIGNATURE}")
    return Message(subject, text)
