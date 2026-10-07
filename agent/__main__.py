"""Command line.

    python -m agent check                         # validate config, credentials, folders
    python -m agent run                           # poll forever (the service)
    python -m agent poll-once                     # one inbox check, then exit
    python -m agent process FILE --company KEY    # run one source file by hand (e.g. after a failure)
    python -m agent review list                   # outputs waiting for review (ADR-0017)
    python -m agent review approve ID [--by NAME] [--note TEXT]
    python -m agent review reject ID --reason TEXT [--by NAME]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def _setup_logging(cfg) -> None:
    log_file = cfg.state_file.parent / "service.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout), RotatingFileHandler(
                            log_file, maxBytes=5_000_000, backupCount=5, encoding="utf-8")])  # ~30 MB at most


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env")
    from agent import config as config_mod
    from agent.mail.mailbox import FakeMailbox, from_config
    from agent.service import Service

    p = argparse.ArgumentParser(prog="python -m agent", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", type=Path, default=ROOT / "config.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    sub.add_parser("run")
    sub.add_parser("poll-once")
    pr = sub.add_parser("process")
    pr.add_argument("file", type=Path)
    pr.add_argument("--company", required=True)
    pr.add_argument("--no-email", action="store_true", help="print notifications instead of sending")
    rv = sub.add_parser("review", help="list, approve or reject outputs waiting for review")
    rv.add_argument("action", choices=["list", "approve", "reject"])
    rv.add_argument("id", nargs="?")
    rv.add_argument("--by", default="", help="reviewer name (default: the Windows user)")
    rv.add_argument("--note", default="")
    rv.add_argument("--reason", default="", help="required for reject")
    rv.add_argument("--no-email", action="store_true", help="print notifications instead of sending")
    a = p.parse_args(argv)

    cfg = config_mod.load(a.config)
    problems = config_mod.check(cfg, need_mail=not (a.cmd in ("process", "review") and a.no_email))
    if a.cmd == "check":
        print("\n".join(f"  ✗ {x}" for x in problems) or "  ✓ configuration OK")
        for c in cfg.companies.values():
            print(f"  company {c.key}: pipeline={c.pipeline} senders={len(c.senders)} -> "
                  f"{cfg.destination(c.key, 2026) if c.pipeline else '(dashboard only)'}")
        return 1 if problems else 0
    if problems:
        print("Refusing to start:\n" + "\n".join(f"  - {x}" for x in problems), file=sys.stderr)
        return 2
    _setup_logging(cfg)

    if a.cmd == "process":
        company = cfg.companies.get(a.company)
        if company is None:
            print(f"unknown company {a.company!r}; known: {sorted(cfg.companies)}", file=sys.stderr)
            return 2
        mailbox = FakeMailbox() if a.no_email else from_config(cfg.mail)
        svc = Service(cfg, mailbox)
        src = a.file.resolve()
        from agent.workbook.reader import TradingUpdate
        year = TradingUpdate(src).iso_week[0]
        dest = cfg.destination(company.key, year)
        result = (svc.process_file(company, src) if src.parent == dest
                  else svc.process_attachment(company, src.name, src.read_bytes(), year))
        if a.no_email:
            for m in mailbox.sent:
                print(f"\n--- email: {m['subject']}\n{m['text']}")
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("status") in ("pending_review", "duplicate") else 1

    if a.cmd == "review":
        from agent.publishing.review import ReviewError, ReviewQueue
        queue = ReviewQueue(cfg.review_dir)
        if a.action == "list":
            for i in queue.items():
                waiting = f" (decision waiting: {i.requested['decision']})" if i.requested and i.status == "pending" else ""
                print(f"{i.status:<15} {i.id:<45} {i.label}  checks {i.checks_passed}/{i.checks_total}{waiting}")
            return 0
        if not a.id:
            print("review approve/reject needs an ID (see: python -m agent review list)", file=sys.stderr)
            return 2
        mailbox = FakeMailbox() if a.no_email else from_config(cfg.mail)
        try:
            queue.request(a.id, a.action, a.by, a.reason if a.action == "reject" else a.note)
        except ReviewError as e:
            print(e, file=sys.stderr)
            return 1
        done = Service(cfg, mailbox).apply_decisions()
        for m in getattr(mailbox, "sent", []):
            print(f"\n--- email: {m['subject']}\n{m['text']}")
        print(json.dumps(done, indent=2, default=str))
        return 0 if all(d["status"] in ("approved", "rejected") for d in done) else 1

    svc = Service(cfg, from_config(cfg.mail))
    if a.cmd == "poll-once":
        print(json.dumps(svc.poll_once(), indent=2, default=str))
        return 0
    svc.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
