"""The service's memory between polls: which emails were handled, which weeks are on hold, and inbox health.

Persisted as JSON in ``state_file`` (default ``data/state.json``). Each email is handled exactly once
because its Message-ID is recorded here; the dashboard reads the same file for the processing log
and the inbox status.
"""
from __future__ import annotations

import json
from pathlib import Path


class State:
    """Processed Message-IDs, weeks on hold and inbox health, persisted as JSON."""

    def __init__(self, path: Path):
        self.path = path
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        self.processed: dict[str, dict] = data.get("processed", {})
        # source path -> {company, year, cw, reason, since}: weeks waiting for last week to be published
        self.held: dict[str, dict] = data.get("held", {})
        # last_ok, and while the inbox can't be read: failures, failing_since, last_error, alerted
        self.inbox: dict = data.get("inbox", {})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"processed": self.processed, "held": self.held, "inbox": self.inbox},
                                  indent=2), encoding="utf-8")
        tmp.replace(self.path)
