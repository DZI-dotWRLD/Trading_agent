"""Service configuration: config.yaml + one companies/<name>.yaml per portfolio company.

Paths in config.yaml are relative to the config file's folder unless absolute.
Secrets (API key, mail password) live in .env and are referenced by env-var name.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


class ConfigError(Exception):
    pass


@dataclass
class Company:
    key: str  # folder name under ROOT, e.g. "Inceptua"
    display_name: str
    senders: list[str]
    filename_pattern: str
    assumptions: dict = field(default_factory=dict)
    panels: list[str] = field(default_factory=list)
    pipeline: bool = True  # False = dashboard-only company (no weekly skill)
    name: str = ""  # the name used inside its workbooks' labels, e.g. "Inceptua"; defaults to key (ADR-0017)
    style_template: Path | None = None  # the look of its generated tabs; None = the house style (ADR-0021)

    def __post_init__(self) -> None:
        self.name = self.name or self.key

    def matches_file(self, name: str) -> bool:
        return re.fullmatch(self.filename_pattern, name, re.IGNORECASE) is not None


@dataclass
class MailConfig:
    type: str = "imap"  # imap (Gmail, any password-login IMAP) or graph (Microsoft 365)
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    user_env: str = "MAIL_USER"  # the mailbox address (both types)
    password_env: str = "MAIL_APP_PASSWORD"
    tenant_id_env: str = "GRAPH_TENANT_ID"  # graph only: the app registration VSCP's admin creates
    client_id_env: str = "GRAPH_CLIENT_ID"
    client_secret_env: str = "GRAPH_CLIENT_SECRET"
    folder: str = "INBOX"
    lookback_days: int = 7

    @property
    def user(self) -> str:
        return os.environ.get(self.user_env, "")

    @property
    def password(self) -> str:
        return os.environ.get(self.password_env, "")

    @property
    def tenant_id(self) -> str:
        return os.environ.get(self.tenant_id_env, "")

    @property
    def client_id(self) -> str:
        return os.environ.get(self.client_id_env, "")

    @property
    def client_secret(self) -> str:
        return os.environ.get(self.client_secret_env, "")

    def missing_credentials(self) -> list[str]:
        """Names of the .env variables this mailbox type needs but that are empty."""
        if self.type == "graph":
            need = (self.user_env, self.tenant_id_env, self.client_id_env, self.client_secret_env)
        else:
            need = (self.user_env, self.password_env)
        return [n for n in need if not os.environ.get(n, "")]


@dataclass
class Config:
    root: Path
    path_template: str
    runs_dir: Path
    state_file: Path
    poll_minutes: float
    timezone: str
    notify_to: list[str]
    dashboard_url: str
    mail: MailConfig
    agent: dict
    companies: dict[str, Company]
    review_dir: Path | None = None  # outputs waiting for a reviewer; must be outside root (ADR-0017)

    def __post_init__(self) -> None:
        self.review_dir = self.review_dir or self.state_file.parent / "review"

    def destination(self, company: str, year: int) -> Path:
        """Resolve PATH_TEMPLATE (ADR-0004). The result must stay inside ROOT."""
        p = Path(self.path_template.format(root=self.root, company=company, year=year)).resolve()
        try:
            p.relative_to(self.root.resolve())
        except ValueError:
            raise ConfigError(f"path_template resolves outside root: {p}")
        return p

    def company_folder(self, company: str) -> Path:
        return (self.root / company).resolve()

    def source_map_path(self, company: str) -> Path:
        """Where a company's approved source map is kept (ADR-0024): next to state.json, outside the drive."""
        return self.state_file.parent / "source_maps" / f"{company}.json"


def _path(base: Path, v: str) -> Path:
    p = Path(os.path.expandvars(v))
    return p if p.is_absolute() else (base / p)


def load(path: str | Path = "config.yaml") -> Config:
    path = Path(path).resolve()
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    base = path.parent
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    try:
        root = _path(base, raw["root"])
        companies_dir = _path(base, raw.get("companies_dir", "companies"))
    except KeyError as e:
        raise ConfigError(f"config.yaml is missing {e}") from e

    companies: dict[str, Company] = {}
    for f in sorted(companies_dir.glob("*.yaml")):
        c = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        comp = Company(
            key=c["key"], display_name=c.get("display_name", c["key"]), name=c.get("name") or c["key"],
            senders=[s.strip().lower() for s in c.get("senders", []) if s and s.strip()],
            filename_pattern=c.get("filename_pattern", r"Trading_update_CW\d{2}_\d{4}(_r\d+)?\.xls[xm]"),
            assumptions=c.get("assumptions", {}) or {}, panels=c.get("panels", []) or [],
            pipeline=c.get("pipeline", True),
            style_template=_path(base, c["style_template"]) if c.get("style_template") else None,
        )
        companies[comp.key] = comp

    cfg = Config(
        root=root,
        path_template=raw.get("path_template", "{root}/{company}/Trading Updates/{year}"),
        runs_dir=_path(base, raw.get("runs_dir", "data/_runs")),
        state_file=_path(base, raw.get("state_file", "data/state.json")),
        poll_minutes=float(raw.get("poll_minutes", 5)),
        timezone=raw.get("timezone", "America/New_York"),
        notify_to=[s for s in raw.get("notify", {}).get("to", []) if s],
        dashboard_url=raw.get("dashboard_url") or "",
        mail=MailConfig(**(raw.get("mailbox", {}) or {})),
        agent=raw.get("agent", {}) or {},
        companies=companies,
        review_dir=_path(base, raw["review_dir"]) if raw.get("review_dir") else None,
    )
    return cfg


def check(cfg: Config, need_mail: bool = True) -> list[str]:
    """Problems that must stop the service from starting (ADR-0008: no empty allowlist)."""
    problems = []
    if "change_me" in str(cfg.root).lower():
        problems.append("set root in config.yaml to the shared drive's Portfolio folder")
    elif not cfg.root.exists():
        problems.append(f"root folder does not exist: {cfg.root}")
    pipeline = [c for c in cfg.companies.values() if c.pipeline]
    if not pipeline:
        problems.append("no companies with pipeline: true in companies/")
    for c in pipeline:
        if not c.senders:
            problems.append(f"{c.key}: sender allowlist is empty (refusing to accept files from anyone)")
        if c.style_template is not None and not c.style_template.exists():
            problems.append(f"{c.key}: style_template not found: {c.style_template}")
        missing = [k for k in ("model_start_date", "po_advance_rate") if c.assumptions.get(k) in (None, "")]
        if missing:  # a company's financing terms are never borrowed from another company (ADR-0024)
            problems.append(f"{c.key}: assumptions missing {', '.join(missing)} (its own financing terms)")
    if not cfg.notify_to:
        problems.append("notify.to is empty: nobody would be told about reports or failures")
    placeholders = [a for a in cfg.notify_to + [s for c in pipeline for s in c.senders] if "change_me" in a.lower()]
    if placeholders:
        problems.append(f"replace the placeholder addresses in config.yaml / companies/*.yaml: {', '.join(placeholders)}")
    for c in cfg.companies.values():  # a profile copied from company_template/ and not filled in yet
        fields = {"key": c.key, "display_name": c.display_name, "name": c.name,
                  **{f"assumptions.{k}": v for k, v in c.assumptions.items()}}
        unfilled = [k for k, v in fields.items() if "change_me" in str(v).lower()]
        if unfilled:
            problems.append(f"{c.key}: fill in the CHANGE_ME values in its companies/*.yaml file: {', '.join(unfilled)}")
    if need_mail and cfg.mail.type not in ("imap", "graph"):
        problems.append(f"mailbox.type must be imap or graph, not {cfg.mail.type!r}")
    elif need_mail and cfg.mail.missing_credentials():
        problems.append(f"mail credentials missing: set {' and '.join(cfg.mail.missing_credentials())} in .env")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        problems.append("ANTHROPIC_API_KEY is not set in .env")
    for name, folder, why in (("runs_dir", cfg.runs_dir, "agent workspaces"),
                              ("review_dir", cfg.review_dir, "unapproved outputs")):
        if folder.resolve().is_relative_to(cfg.root.resolve()):
            problems.append(f"{name} must be outside root ({why} must not live on the shared drive)")
    return problems
