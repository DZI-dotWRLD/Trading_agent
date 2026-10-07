"""Writing to VSCP's file system: add-only saves and a tamper check (ADR-0004, ADR-0013).

Only the orchestrator writes to the shared drive, and only by adding new files.
Around every agent run the whole drive is snapshotted; any change other than
the files the orchestrator itself adds fails the run (see agent.service).
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

REVISION_RE = re.compile(r"^(?P<stem>.+?)(?:_r(?P<rev>\d+))?$")


class StorageError(Exception):
    pass


@dataclass
class Saved:
    path: Path
    revision: int  # 1 = first file for this week, 2 = "_r2", ...
    duplicate: bool = False  # identical bytes already saved; nothing written


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save_new(folder: Path, filename: str, data: bytes) -> Saved:
    """Save ``data`` as ``filename`` in ``folder`` without ever overwriting.

    Same bytes already present (any revision) -> duplicate, nothing written.
    Different bytes -> next free revision: name.xlsx, name_r2.xlsx, name_r3.xlsx ...
    """
    name = Path(filename).name  # never trust a path from an email
    if not name or name in (".", ".."):
        raise StorageError(f"bad attachment name: {filename!r}")
    stem, suffix = Path(name).stem, Path(name).suffix
    folder.mkdir(parents=True, exist_ok=True)
    digest = _sha256(data)
    rev = 1
    while True:
        candidate = folder / (f"{stem}{suffix}" if rev == 1 else f"{stem}_r{rev}{suffix}")
        if not candidate.exists():
            break
        if _sha256(candidate.read_bytes()) == digest:
            return Saved(candidate, rev, duplicate=True)
        rev += 1
    with open(candidate, "xb") as f:  # "x": fail rather than overwrite, even in a race
        f.write(data)
    return Saved(candidate, rev)


def publish_copy(src: Path, dest: Path) -> Path:
    """Copy a finished file onto the drive; refuse to overwrite."""
    if dest.exists():
        raise StorageError(f"{dest} already exists; not overwritten")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.partial")
    shutil.copy2(src, tmp)
    os.replace(tmp, dest)  # atomic on the same volume: readers never see half a file
    return dest


def revision_of(path: Path) -> int:
    m = REVISION_RE.match(path.stem.removesuffix("_vClaude"))
    return int(m.group("rev") or 1) if m else 1


# --------------------------------------------------------------------------- tamper check
Snapshot = dict[str, tuple[int, int]]  # relative path -> (size, mtime_ns)


def snapshot(root: Path) -> Snapshot:
    """Cheap fingerprint of every file under ``root`` (size + modification time)."""
    out: Snapshot = {}
    for dirpath, _, files in os.walk(root):
        for f in files:
            p = Path(dirpath) / f
            try:
                st = p.stat()
            except OSError:
                continue
            out[p.relative_to(root).as_posix()] = (st.st_size, st.st_mtime_ns)
    return out


@dataclass
class Changes:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)

    @property
    def any(self) -> bool:
        return bool(self.added or self.removed or self.modified)

    def describe(self, limit: int = 10) -> str:
        parts = []
        for label, items in (("deleted", self.removed), ("modified", self.modified), ("added", self.added)):
            if items:
                shown = ", ".join(items[:limit]) + (f" (+{len(items) - limit} more)" if len(items) > limit else "")
                parts.append(f"{label}: {shown}")
        return "; ".join(parts) or "no changes"


def diff(before: Snapshot, after: Snapshot, allowed_new: set[str] = frozenset()) -> Changes:
    c = Changes()
    for k, v in after.items():
        if k not in before:
            if k not in allowed_new:
                c.added.append(k)
        elif before[k] != v:
            c.modified.append(k)
    c.removed = sorted(k for k in before if k not in after)
    c.added.sort()
    c.modified.sort()
    return c
