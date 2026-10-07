"""The review queue: validated outputs wait here for a team member's decision (ADR-0017).

    service:   validated output -> submit() -> "waiting for review" email
    dashboard: Approve / Reject  -> request()   (writes a decision file, nothing else)
    service:   apply_decisions() -> approve: verify hash, publish add-only, metrics.json, "published" email
                                 -> reject:  record reason, "rejected" email; nothing reaches the drive

The queue lives outside ROOT (``review_dir``, checked at start-up). One folder per item:

    <review_dir>/<id>/item.json            what was built, the checks, the decision
    <review_dir>/<id>/<output>.xlsx        the validated, recalculated output (the only file ever published)
    <review_dir>/<id>/<output>.metrics.json
    <review_dir>/<id>/decision.json        written once by request(); "x" mode makes a second decision fail

Only the service writes to the drive, so the dashboard needs neither write access to it nor mail
credentials. Before publishing, the output's SHA-256 must still match the one recorded at submit,
and the target must be inside the company's own folder.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import os
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

PENDING, APPROVED, REJECTED, FAILED = "pending", "approved", "rejected", "publish_failed"


class ReviewError(Exception):
    pass


@dataclass
class ReviewItem:
    id: str
    company: str  # company key
    display_name: str
    cw: int
    year: int
    revision: int
    source: str  # absolute path of the saved source file on the drive
    output_name: str
    sha256: str
    created_at: str
    status: str = PENDING
    checks_passed: int = 0
    checks_total: int = 0
    warnings: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)  # where Claude says each typed-in value came from
    cost_usd: float | None = None
    run_dir: str | None = None
    changed_elsewhere: list[str] = field(default_factory=list)
    decided_by: str | None = None
    decided_at: str | None = None
    note: str = ""
    published: str | None = None
    error: str | None = None
    # How the company's file was read (ADR-0024): {"origin": template|approved|discovered, "map": {...},
    # "evidence": {...}}. A discovered map becomes the company's map when this report is approved.
    layout: dict | None = None

    folder: Path = field(default=Path(), repr=False, compare=False)

    @property
    def output_path(self) -> Path:
        return self.folder / self.output_name

    @property
    def metrics_path(self) -> Path:
        return self.folder / f"{Path(self.output_name).stem}.metrics.json"

    @property
    def metrics(self) -> dict:
        try:
            return json.loads(self.metrics_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    @property
    def requested(self) -> dict | None:
        """The decision a reviewer asked for, if the service hasn't applied it yet."""
        p = self.folder / "decision.json"
        try:
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
        except (OSError, json.JSONDecodeError):
            return None

    @property
    def label(self) -> str:
        return f"{self.display_name} CW{self.cw:02d} {self.year}" + (f" (rev {self.revision})" if self.revision > 1 else "")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class ReviewQueue:
    def __init__(self, folder: Path):
        self.folder = Path(folder)

    # ------------------------------------------------------------------ reading
    def items(self, status: str | None = None) -> list[ReviewItem]:
        out = []
        if self.folder.exists():
            for d in self.folder.iterdir():
                item = self._load(d)
                if item and (status is None or item.status == status):
                    out.append(item)
        return sorted(out, key=lambda i: i.created_at, reverse=True)

    def get(self, item_id: str) -> ReviewItem:
        if not item_id or Path(item_id).name != item_id or item_id in (".", ".."):
            raise ReviewError(f"bad review id {item_id!r}")
        item = self._load(self.folder / item_id)
        if item is None:
            raise ReviewError(f"no review item {item_id!r}")
        return item

    def for_source(self, source: Path) -> list[ReviewItem]:
        src = str(Path(source).resolve())
        return [i for i in self.items() if i.source == src]

    def _load(self, d: Path) -> ReviewItem | None:
        try:
            data = json.loads((d / "item.json").read_text(encoding="utf-8"))
            return ReviewItem(**data, folder=d)
        except (OSError, json.JSONDecodeError, TypeError):
            return None

    def _save(self, item: ReviewItem) -> None:
        data = {k: v for k, v in asdict(item).items() if k != "folder"}
        tmp = item.folder / "item.json.partial"
        tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        os.replace(tmp, item.folder / "item.json")

    # ------------------------------------------------------------------ service: add an item
    def submit(self, *, company, source: Path, validated: Path, output_name: str, cw: int, year: int, revision: int,
               metrics: dict, validation: dict | None = None, agent_report: dict | None = None,
               cost_usd: float | None = None, run_dir: Path | None = None,
               changed_elsewhere: list[str] | None = None, layout: dict | None = None) -> ReviewItem:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        item_id = f"{company.key}-CW{cw:02d}-{year}-r{revision}-{stamp}".replace(" ", "_")
        d = self.folder / item_id
        d.mkdir(parents=True, exist_ok=False)
        shutil.copy2(validated, d / output_name)
        checks = (validation or {}).get("checks", [])
        item = ReviewItem(
            id=item_id, company=company.key, display_name=company.display_name, cw=cw, year=year, revision=revision,
            source=str(Path(source).resolve()), output_name=output_name, sha256=_sha256(d / output_name),
            created_at=_now(), checks_passed=sum(1 for c in checks if c.get("passed")), checks_total=len(checks),
            warnings=list((agent_report or {}).get("warnings", [])) + [
                f"{c['name']}: {c.get('detail', '')}" for c in checks if not c.get("passed")],
            sources=list((agent_report or {}).get("sources", [])), cost_usd=cost_usd,
            run_dir=str(run_dir) if run_dir else None, changed_elsewhere=list(changed_elsewhere or []),
            layout=layout, folder=d)
        (d / item.metrics_path.name).write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")
        self._save(item)
        return item

    # ------------------------------------------------------------------ dashboard: ask for a decision
    def request(self, item_id: str, decision: str, reviewer: str = "", note: str = "") -> ReviewItem:
        """Record a reviewer's decision. The service applies it; this never touches the drive."""
        if decision not in ("approve", "reject"):
            raise ReviewError(f"unknown decision {decision!r}")
        if decision == "reject" and not note.strip():
            raise ReviewError("a rejection needs a reason")
        item = self.get(item_id)
        if item.status != PENDING:
            raise ReviewError(f"{item.label} is already {item.status}")
        body = {"decision": decision, "reviewer": reviewer.strip() or getpass.getuser(),
                "windows_user": getpass.getuser(), "note": note.strip(), "at": _now()}
        try:
            with open(item.folder / "decision.json", "x", encoding="utf-8") as f:  # first decision wins
                json.dump(body, f, indent=2)
        except FileExistsError:
            raise ReviewError(f"{item.label} already has a decision waiting to be applied") from None
        return item

    # ------------------------------------------------------------------ service: carry decisions out
    def apply(self, item: ReviewItem, company_folder: Path) -> ReviewItem:
        """Apply a requested decision. Approve publishes to the source's folder, add-only."""
        from agent.publishing.report_metrics import write_metrics
        from agent.publishing.storage import StorageError, publish_copy

        req = item.requested
        if item.status != PENDING or not req:
            return item
        item.decided_by, item.decided_at, item.note = req.get("reviewer"), req.get("at"), req.get("note", "")
        if req["decision"] == "reject":
            item.status = REJECTED
            self._save(item)
            return item
        try:
            if _sha256(item.output_path) != item.sha256:
                raise ReviewError("the queued output changed after it was validated; not published")
            target_dir = Path(item.source).parent.resolve()
            if not target_dir.is_relative_to(Path(company_folder).resolve()):
                raise ReviewError(f"{target_dir} is outside the company's folder; not published")
            target = target_dir / item.output_name
            if target.exists() and _sha256(target) == item.sha256:
                out = target  # an earlier apply published it but stopped (crash, restart) before recording that
            else:
                out = publish_copy(item.output_path, target)
            metrics = {**item.metrics, "approved_by": item.decided_by, "approved_at": item.decided_at,
                       "review_id": item.id}
            write_metrics(out, metrics)
            item.status, item.published = APPROVED, str(out)
        except (ReviewError, StorageError, OSError) as e:
            item.status, item.error = FAILED, str(e)
        self._save(item)
        return item
