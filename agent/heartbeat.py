"""The service's sign of life for the dashboard: ``heartbeat.json`` next to ``state.json``.

The running service rewrites it every loop (about every 10 s), and before and after each weekly run, so
the dashboard can tell "running", "processing a report" and "not running" apart without talking to the
service. A clean stop records ``stopped_at``; a crash or a closed window just lets the file go stale.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

IDLE_STALE_SECONDS = 120        # the loop writes every ~10 s; two minutes of silence means it is not running
BUSY_STALE_SECONDS = 45 * 60    # a weekly run blocks the loop; one run plus a retry stays well inside this


def path_for(state_file: Path) -> Path:
    return state_file.with_name("heartbeat.json")


class Heartbeat:
    """Written only by the service."""

    def __init__(self, path: Path, poll_minutes: float, started: datetime):
        self.path = path
        self.data = {"pid": os.getpid(), "started": started.isoformat(timespec="seconds"),
                     "poll_minutes": poll_minutes, "seen": None, "last_poll": None, "busy": None, "stopped_at": None}

    def beat(self, now: datetime, **changes) -> None:
        self.data.update(changes, seen=now.isoformat(timespec="seconds"))
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass  # the dashboard's status line must never stop the service


def read_status(state_file: Path, now: datetime) -> dict:
    """What the dashboard shows: state = running | busy | stopped | not_running | unknown, plus the times."""
    try:
        hb = json.loads(path_for(state_file).read_text(encoding="utf-8"))
        seen = datetime.fromisoformat(hb["seen"])
    except (OSError, ValueError, KeyError, TypeError):
        return {"state": "unknown"}
    age = (now - seen).total_seconds()
    out = {"seen": hb["seen"], "last_poll": hb.get("last_poll"), "started": hb.get("started"),
           "busy": hb.get("busy"), "age_seconds": age}
    if hb.get("stopped_at"):
        out["state"] = "stopped"
    elif hb.get("busy"):
        out["state"] = "busy" if age <= BUSY_STALE_SECONDS else "not_running"
    else:
        out["state"] = "running" if age <= IDLE_STALE_SECONDS else "not_running"
    return out
