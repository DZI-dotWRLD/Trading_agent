"""The always-on service: poll the inbox, save, run, check, queue for review, publish (ADR-0003, ADR-0017).

    email -> recognise -> save source (add-only) -> snapshot drive -> run_week (agent + validator)
          -> snapshot again: nothing but new files? -> review queue -> "review needed" email
    reviewer approves in the dashboard -> apply_decisions(): publish output + metrics.json -> "approved" email
    reviewer rejects -> nothing published -> "rejected" email
    any failure -> nothing queued or published -> "ACTION NEEDED" email

The service is the only writer to the drive: the dashboard only records decisions in the queue.

Tamper check scope: the company's own folder is strict (any change fails the run);
changes elsewhere under ROOT are reported in the email but do not block, since
colleagues legitimately save files on a shared drive while a run is in progress.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from agent import heartbeat
from agent.claude.memory.prior import find_prior_report
from agent.claude.memory.state import State
from agent.claude.runner import run_skill
from agent.config import Company, Config
from agent.mail import notify
from agent.mail.mailbox import Attachment, Email, Mailbox
from agent.mail.recognition import recognise
from agent.pipeline import output_name, run_week
from agent.publishing.report_metrics import build_metrics
from agent.publishing.review import APPROVED, PENDING, REJECTED, ReviewQueue
from agent.publishing.storage import diff, revision_of, save_new, snapshot
from agent.workbook import source_map as maps
from agent.workbook.reader import TradingUpdate, WorkbookError

log = logging.getLogger("vscp.service")
DECISION_CHECK_SECONDS = 10  # how quickly an Approve click in the dashboard is carried out
INBOX_ALERT_AFTER = 3  # failed polls in a row before the team is told the inbox can't be read


class Service:
    def __init__(self, cfg: Config, mailbox: Mailbox, run_agent: Callable = run_skill,
                 clock: Callable[[], datetime] | None = None, discover: Callable | None = None):
        self.cfg, self.mailbox, self.run_agent = cfg, mailbox, run_agent
        self.discover = discover  # Claude's layout discovery (agent.claude.discover.run_discovery); tests inject
        self.tz = ZoneInfo(cfg.timezone)
        self.clock = clock or (lambda: datetime.now(self.tz))
        self.state = State(cfg.state_file)
        self.queue = ReviewQueue(cfg.review_dir)
        self.heartbeat = heartbeat.Heartbeat(heartbeat.path_for(cfg.state_file), cfg.poll_minutes, self.clock())
        self.serving = False  # True inside run_forever: only the running service writes the heartbeat

    # ------------------------------------------------------------------ polling
    def poll_once(self) -> list[dict]:
        results = []
        try:
            mails = self.mailbox.fetch_new(set(self.state.processed))
        except Exception as e:
            self._inbox_failed(e)
            raise
        self._inbox_ok()
        for mail in mails:
            try:
                r = self.handle_email(mail)
            except Exception as e:  # one bad email must never stop the service
                log.exception("error handling %s", mail.message_id)
                r = {"status": "error", "error": f"{type(e).__name__}: {e}"}
            self.state.processed[mail.message_id] = {"at": self.clock().isoformat(timespec="seconds"),
                                                     "sender": mail.sender, "subject": mail.subject, **r}
            self.state.save()
            results.append(r)
        self.release_held()
        return results

    def run_forever(self) -> None:
        log.info("watching %s every %.0f min; companies: %s", self.cfg.mail.user or "mailbox",
                 self.cfg.poll_minutes, ", ".join(c.key for c in self.cfg.companies.values() if c.pipeline))
        next_poll = 0.0
        self.serving = True
        try:
            while True:
                self._beat()
                try:
                    if self.apply_decisions():
                        self.release_held()  # an approval may be what a held week was waiting for
                except Exception:
                    log.exception("applying review decisions failed; will retry")
                if time.monotonic() >= next_poll:
                    try:
                        self.poll_once()
                        self._beat(last_poll=self.clock().isoformat(timespec="seconds"))
                    except Exception:
                        log.exception("poll failed; will retry next cycle")
                    next_poll = time.monotonic() + self.cfg.poll_minutes * 60
                time.sleep(DECISION_CHECK_SECONDS)
        finally:  # Ctrl+C or a clean stop; a crash that kills the process just leaves the heartbeat to go stale
            self._beat(busy=None, stopped_at=self.clock().isoformat(timespec="seconds"))

    def _beat(self, **changes) -> None:
        if self.serving:
            self.heartbeat.beat(self.clock(), **changes)

    # ------------------------------------------------------------------ one email
    def handle_email(self, mail: Email) -> dict:
        verdict = recognise(mail, self.cfg.companies)
        if not verdict.accepted:
            log.info("ignored %s from %s: %s", mail.message_id, mail.sender, verdict.reason)
            return {"status": "ignored", "reason": verdict.reason}
        runs = []
        for m in verdict.matches:
            runs.append(self.process_attachment(m.company, m.attachment.filename, m.attachment.data, m.year))
        return {"status": "processed", "runs": runs}

    def process_attachment(self, company: Company, filename: str, data: bytes, year: int) -> dict:
        dest = self.cfg.destination(company.key, year)
        saved = save_new(dest, filename, data)
        log.info("%s %s (revision %d)", "duplicate of" if saved.duplicate else "saved", saved.path, saved.revision)
        if saved.duplicate and ((saved.path.parent / output_name(saved.path)).exists() or any(
                i.status in (PENDING, APPROVED, REJECTED) for i in self.queue.for_source(saved.path))):
            return {"status": "duplicate", "source": str(saved.path)}
        return self.process_file(company, saved.path)

    # ------------------------------------------------------------------ one source file
    def process_file(self, company: Company, source: Path) -> dict:
        try:
            layout = self._layout(company, source)
        except _LayoutUnknown as e:
            return self._fail(company, None, None, source, e.reason, e.details, e.log_dir)
        try:
            year, cw = TradingUpdate(source, layout["map"]).iso_week
        except (WorkbookError, Exception) as e:
            return self._fail(company, None, None, source, "the attachment is not a readable trading update",
                              [f"{type(e).__name__}: {e}"], None)

        gate = self._readiness(company, source, year, cw)
        if gate is not None:
            kind, reason = gate
            if kind == "fail":
                return self._fail(company, cw, year, source, reason, [], None)
            return self._hold(company, source, year, cw, reason)

        company_dir = self.cfg.company_folder(company.key)
        before = snapshot(self.cfg.root)
        log.info("running %s CW%02d %d", company.key, cw, year)
        self._beat(busy=f"{company.display_name} CW{cw:02d} {year}")
        try:
            res = run_week(source, company=company.key, reports_dir=source.parent,
                           runs_dir=self.cfg.runs_dir / company.key, publish_dir=None,
                           assumptions=company.assumptions, run_agent=self.run_agent,
                           agent_kwargs=self.cfg.agent or None, company_name=company.name,
                           style_template=company.style_template, source_map=layout["map"])
        finally:
            self._beat(busy=None)
        log_dir = Path(res.attempts[-1]["work_dir"]) if res.attempts else None

        changes = diff(before, snapshot(self.cfg.root))
        rel = company_dir.relative_to(self.cfg.root.resolve()).as_posix() + "/" if company_dir.is_relative_to(
            self.cfg.root.resolve()) else ""
        inside = [p for p in changes.removed + changes.modified + changes.added if p.startswith(rel)]
        elsewhere = [p for p in changes.removed + changes.modified + changes.added if not p.startswith(rel)]
        if inside:
            return self._fail(company, cw, year, source,
                              "files in the company folder changed during the run; nothing was published",
                              [f"changed: {p}" for p in inside], log_dir, tamper=True)
        if not res.ok:
            v = res.last_validation or {}
            failed = [f"{c['name']}: {c['detail']}" for c in v.get("checks", []) if not c["passed"]
                      and c["severity"] == "error"]
            return self._fail(company, cw, year, source, res.error.splitlines()[0] if res.error else "run failed",
                              failed, log_dir)

        if (source.parent / output_name(source)).exists():  # ADR-0013: never overwrite a published file
            return self._fail(company, cw, year, source, f"{output_name(source)} already exists; not overwritten",
                              [], log_dir)
        agent = res.attempts[-1].get("agent", {})
        try:
            report = json.loads((log_dir / "agent_report.json").read_text(encoding="utf-8")) if log_dir else {}
        except (OSError, json.JSONDecodeError):
            report = {}
        metrics = build_metrics(res.validated, res.context, source.parent, company.key, revision_of(source))
        cost = (agent.get("cost_usd") or 0.0) + (layout.get("cost_usd") or 0.0) or None
        item = self.queue.submit(
            company=company, source=source, validated=res.validated, output_name=output_name(source), cw=cw,
            year=year, revision=revision_of(source), metrics=metrics, validation=res.last_validation,
            agent_report=report, cost_usd=cost, run_dir=log_dir, changed_elsewhere=elsewhere,
            layout={k: layout.get(k) for k in ("origin", "map", "evidence", "checks")})
        self._send(notify.review_needed(item, self.cfg.dashboard_url or None))
        log.info("queued %s for review (%s)", item.output_name, item.id)
        return {"status": "pending_review", "review_id": item.id, "cost_usd": agent.get("cost_usd"),
                "changed_elsewhere": elsewhere}

    # ------------------------------------------------------------------ the company's layout (ADR-0024)
    def _layout(self, company: Company, source: Path) -> dict:
        """How to read this file: {"origin", "map", "evidence", "checks", "cost_usd"}.

        The company's approved map, else a map Claude proposed earlier that still awaits approval, else the
        template's own layout, whichever fits this file (resolves and passes the map checks). Only when none
        does is Claude asked to work the layout out; code checks its map again before it is used.
        """
        import openpyxl

        from agent.workbook.map_check import check_map
        wb = openpyxl.load_workbook(source, data_only=True)
        approved, pending = self.cfg.source_map_path(company.key), self._pending_map_path(company)
        candidates = [(maps.load(approved), "approved")] if approved.exists() else []
        if pending.exists():
            candidates.append((maps.load(pending), "discovered"))
        candidates.append((maps.default_map(), "template"))
        for m, origin in candidates:
            errors = [c for c in check_map(wb, m) if not c.passed and c.severity == "error"]
            if not errors:
                return {"origin": origin, "map": m, "evidence": m.get("evidence"), "checks": None, "cost_usd": None}
            log.info("%s map for %s does not fit %s: %s", origin, company.key, source.name,
                     "; ".join(f"{c.name}: {c.detail}"[:120] for c in errors[:3]))

        # An unfamiliar layout: Claude reads the file and proposes a map; code checks it independently.
        discover = self.discover
        if discover is None:
            from agent.claude.discover import run_discovery as discover
        work = self.cfg.runs_dir / company.key / f"{source.stem}-layout-{self.clock().strftime('%Y%m%d-%H%M%S')}"
        log.info("unfamiliar layout for %s; asking Claude to map %s", company.key, source.name)
        self._beat(busy=f"{company.display_name}: learning a new file layout")
        try:
            found = discover(source, work, company.name)
        finally:
            self._beat(busy=None)
        if not found.ok or found.source_map is None:
            failed = [f"{c.name}: {c.detail}" for c in (found.checks or []) if not c.passed and c.severity == "error"]
            raise _LayoutUnknown("the file's layout could not be mapped to the trading-update inputs",
                                 ([found.error] if found.error else []) + failed + ([found.final_text[:300]]
                                                                                    if found.final_text else []), work)
        maps.save(found.source_map, pending)
        log.info("Claude mapped %s's layout (cost $%.2f); it waits for approval with the report",
                 company.key, found.cost_usd or 0)
        return {"origin": "discovered", "map": found.source_map, "evidence": found.source_map.get("evidence"),
                "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail, "severity": c.severity}
                           for c in found.checks], "cost_usd": found.cost_usd}

    def _pending_map_path(self, company: Company) -> Path:
        return self.cfg.source_map_path(company.key).with_suffix(".pending.json")

    def _adopt_map(self, item) -> None:
        """The reviewer approved a report built from Claude's map: it is now the company's map."""
        company = self.cfg.companies[item.company]
        maps.save(item.layout["map"], self.cfg.source_map_path(company.key))
        self._pending_map_path(company).unlink(missing_ok=True)
        log.info("source map for %s approved with %s", company.key, item.id)

    # ------------------------------------------------------------------ review decisions
    def apply_decisions(self) -> list[dict]:
        """Carry out Approve / Reject clicks recorded in the review queue. Only this writes to the drive."""
        done = []
        for item in self.queue.items(PENDING):
            if not item.requested:
                continue
            if item.company not in self.cfg.companies:
                log.error("review %s: unknown company %r; ignored", item.id, item.company)
                continue
            item = self.queue.apply(item, self.cfg.company_folder(item.company))
            if (item.layout or {}).get("origin") == "discovered" and item.company in self.cfg.companies:
                if item.status == APPROVED:
                    self._adopt_map(item)
                elif item.status == REJECTED:  # maybe the map was wrong: the next file is mapped afresh
                    self._pending_map_path(self.cfg.companies[item.company]).unlink(missing_ok=True)
            if item.status == APPROVED:
                self._send(notify.report_published(item, self.cfg.dashboard_url or None))
                log.info("approved by %s, published %s", item.decided_by, item.published)
            elif item.status == REJECTED:
                self._send(notify.report_rejected(item))
                log.info("rejected by %s: %s (%s)", item.decided_by, item.note, item.id)
            else:
                self._send(notify.publish_failed(item))
                log.error("approved but not published: %s (%s)", item.error, item.id)
            done.append({"id": item.id, "status": item.status, "published": item.published, "error": item.error})
        return done

    # ------------------------------------------------------------------ inbox health
    def _inbox_failed(self, e: Exception) -> None:
        h = self.state.inbox
        h["failures"] = h.get("failures", 0) + 1
        h.setdefault("failing_since", self.clock().isoformat(timespec="seconds"))
        h["last_error"] = f"{type(e).__name__}: {e}"[:300]
        if h["failures"] >= INBOX_ALERT_AFTER and not h.get("alerted"):
            # Sending uses SMTP, which may still work when IMAP doesn't. If it fails too, try again next poll.
            h["alerted"] = self._send(notify.inbox_unreachable(
                self.cfg.mail.user or "the mailbox", h["failing_since"], h["failures"], h["last_error"]))
        self.state.save()

    def _inbox_ok(self) -> None:
        if self.state.inbox.get("alerted"):
            self._send(notify.inbox_recovered(self.cfg.mail.user or "the mailbox", self.state.inbox["failing_since"]))
        self.state.inbox = {"last_ok": self.clock().isoformat(timespec="seconds")}
        self.state.save()

    # ------------------------------------------------------------------ weeks on hold (ADR-0023)
    def _readiness(self, company: Company, source: Path, year: int, cw: int) -> tuple[str, str] | None:
        """None when the week can be built now; else ("hold" | "fail", reason). Never runs Claude.

        The opening loan balance comes from the company profile or, from the second week on, from last week's
        published output. Without either, a run can only fail, so it is held (last week is on its way) or
        failed at once (there is no last week at all).
        """
        if company.assumptions.get("opening_loan_balance_eur") is not None:
            return None
        prior = find_prior_report(source.parent, year, cw)
        if prior is None:
            return ("fail", "this is the company's first report and no opening loan balance is configured; set "
                            "opening_loan_balance_eur in its profile and resend or process the file")
        if (prior.parent / output_name(prior)).exists():
            return None
        items = self.queue.for_source(prior)
        latest = max(items, key=lambda i: i.created_at) if items else None
        label = prior.stem.replace("Trading_update_", "").replace("_", " ")
        held = str(prior.resolve()) in self.state.held
        why = ("is waiting for review" if latest is not None and latest.status == PENDING else
               "was rejected" if latest is not None and latest.status == REJECTED else
               "is itself on hold" if held else "has not been published (its run failed or has not run)")
        return ("hold", f"last week's report ({label}) {why}")

    def _hold(self, company: Company, source: Path, year: int, cw: int, reason: str) -> dict:
        key = str(source.resolve())
        first = key not in self.state.held
        self.state.held[key] = {"company": company.key, "year": year, "cw": cw, "reason": reason,
                                "since": self.state.held.get(key, {}).get("since")
                                or self.clock().isoformat(timespec="seconds")}
        self.state.save()
        if first:
            log.info("on hold %s CW%02d %d: %s", company.key, cw, year, reason)
            self._send(notify.week_on_hold(company.display_name, cw, year, reason))
        return {"status": "held", "reason": reason, "source": key}

    def release_held(self) -> list[dict]:
        """Run every held week whose last week is now published, oldest first."""
        done = []
        for key, h in sorted(self.state.held.items(), key=lambda kv: (kv[1]["year"], kv[1]["cw"])):
            company, source = self.cfg.companies.get(h["company"]), Path(key)
            if company is None or not source.exists():
                self.state.held.pop(key, None)
                self.state.save()
                continue
            gate = self._readiness(company, source, h["year"], h["cw"])
            if gate is not None and gate[0] == "hold":
                if gate[1] != h["reason"]:
                    h["reason"] = gate[1]
                    self.state.save()
                continue
            self.state.held.pop(key, None)
            self.state.save()
            log.info("releasing %s CW%02d %d from hold", company.key, h["cw"], h["year"])
            result = self.process_file(company, source)
            for entry in self.state.processed.values():  # the email's record shows what finally happened
                for i, r in enumerate(entry.get("runs") or []):
                    if r.get("status") == "held" and r.get("source") == key:
                        entry["runs"][i] = {**result, "released_from_hold": h["since"]}
            self.state.save()
            done.append(result)
        return done

    # ------------------------------------------------------------------ helpers
    def _fail(self, company: Company, cw, year, source, reason: str, details: list[str], log_dir,
              tamper: bool = False) -> dict:
        log.error("%s CW%s: %s", company.key, cw, reason)
        self._send(notify.run_failed(company.display_name, cw, year, source, reason, details, log_dir, company.key))
        return {"status": "tamper" if tamper else "failed", "reason": reason, "details": details[:20],
                "source": str(source) if source else None}

    def _send(self, msg: notify.Message) -> bool:
        try:
            attachments = [Attachment(p.name, p.read_bytes()) for p in msg.attachments]
            self.mailbox.send(self.cfg.notify_to, msg.subject, msg.text, msg.html, attachments)
            log.info("emailed %r to %s", msg.subject, ", ".join(self.cfg.notify_to))
            return True
        except Exception:
            log.exception("could not send email %r", msg.subject)
            return False


class _LayoutUnknown(Exception):
    def __init__(self, reason: str, details: list[str], log_dir: Path | None):
        super().__init__(reason)
        self.reason, self.details, self.log_dir = reason, details, log_dir
