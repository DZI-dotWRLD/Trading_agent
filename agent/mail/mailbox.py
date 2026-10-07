"""Mailbox interface and adapters (ADR-0002).

``ImapSmtpMailbox`` works with Gmail (app password) and any IMAP provider that still
accepts password login; Microsoft 365 generally does not, so it uses ``agent.mail.graph.GraphMailbox``
(``type: graph``), which implements the same two methods (fetch_new, send); see docs/NEXT_STEPS.md section 3.
"""
from __future__ import annotations

import imaplib
import smtplib
import ssl
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from typing import Protocol


@dataclass
class Attachment:
    filename: str
    data: bytes


@dataclass
class Email:
    message_id: str
    sender: str  # bare address, lower-case
    subject: str
    received: datetime | None
    attachments: list[Attachment] = field(default_factory=list)


class Mailbox(Protocol):
    def fetch_new(self, seen: set[str]) -> list[Email]:
        """Messages not in ``seen`` (by Message-ID). Must not mark anything read or delete it."""

    def send(self, to: list[str], subject: str, text: str, html: str | None = None,
             attachments: list[Attachment] = ()) -> None: ...


def parse_message(raw: bytes) -> Email:
    msg = message_from_bytes(raw, policy=policy.default)
    mid = (msg.get("Message-ID") or "").strip()
    try:
        received = parsedate_to_datetime(msg["Date"]) if msg["Date"] else None
    except (TypeError, ValueError):
        received = None
    atts = []
    for part in msg.iter_attachments():
        name = part.get_filename()
        if name:
            atts.append(Attachment(name, part.get_payload(decode=True) or b""))
    return Email(mid, parseaddr(msg.get("From", ""))[1].lower(), str(msg.get("Subject", "")), received, atts)


def build_message(sender: str, to: list[str], subject: str, text: str, html: str | None = None,
                  attachments: list[Attachment] = ()) -> EmailMessage:
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = sender, ", ".join(to), subject
    m.set_content(text)
    if html:
        m.add_alternative(html, subtype="html")
    for a in attachments:
        m.add_attachment(a.data, maintype="application",
                         subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=a.filename)
    return m


class ImapSmtpMailbox:
    def __init__(self, user: str, password: str, imap_host: str = "imap.gmail.com", imap_port: int = 993,
                 smtp_host: str = "smtp.gmail.com", smtp_port: int = 465, folder: str = "INBOX",
                 lookback_days: int = 7):
        if not user or not password:
            raise ValueError("mailbox user and password are required")
        self.user, self.password = user, password
        self.imap_host, self.imap_port = imap_host, imap_port
        self.smtp_host, self.smtp_port = smtp_host, smtp_port
        self.folder, self.lookback_days = folder, lookback_days

    def fetch_new(self, seen: set[str]) -> list[Email]:
        since = (datetime.now(timezone.utc) - timedelta(days=self.lookback_days)).strftime("%d-%b-%Y")
        out: list[Email] = []
        with imaplib.IMAP4_SSL(self.imap_host, self.imap_port, ssl_context=ssl.create_default_context()) as imap:
            imap.login(self.user, self.password)
            imap.select(self.folder, readonly=True)  # read-only: never changes flags or deletes
            typ, data = imap.search(None, "SINCE", since)
            if typ != "OK":
                return out
            for num in data[0].split():
                typ, hdr = imap.fetch(num, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
                if typ != "OK" or not hdr or not isinstance(hdr[0], tuple):
                    continue
                mid = message_from_bytes(hdr[0][1]).get("Message-ID", "").strip()
                if not mid or mid in seen:
                    continue
                typ, body = imap.fetch(num, "(BODY.PEEK[])")
                if typ == "OK" and body and isinstance(body[0], tuple):
                    out.append(parse_message(body[0][1]))
        return out

    def send(self, to: list[str], subject: str, text: str, html: str | None = None,
             attachments: list[Attachment] = ()) -> None:
        msg = build_message(self.user, to, subject, text, html, attachments)
        with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, context=ssl.create_default_context()) as s:
            s.login(self.user, self.password)
            s.send_message(msg)


class FakeMailbox:
    """In-memory mailbox for tests and dry runs."""

    def __init__(self, inbox: list[Email] | None = None):
        self.inbox = list(inbox or [])
        self.sent: list[dict] = []

    def fetch_new(self, seen: set[str]) -> list[Email]:
        return [m for m in self.inbox if m.message_id not in seen]

    def send(self, to: list[str], subject: str, text: str, html: str | None = None, attachments=()) -> None:
        self.sent.append({"to": list(to), "subject": subject, "text": text, "html": html,
                          "attachments": [a.filename for a in attachments]})


def from_config(mail_cfg) -> Mailbox:
    if mail_cfg.type == "imap":
        return ImapSmtpMailbox(mail_cfg.user, mail_cfg.password, mail_cfg.imap_host, mail_cfg.imap_port,
                               mail_cfg.smtp_host, mail_cfg.smtp_port, mail_cfg.folder, mail_cfg.lookback_days)
    if mail_cfg.type == "graph":
        from agent.mail.graph import GraphMailbox
        folder = "inbox" if mail_cfg.folder.upper() == "INBOX" else mail_cfg.folder  # Graph's well-known name
        return GraphMailbox(mail_cfg.tenant_id, mail_cfg.client_id, mail_cfg.client_secret, mail_cfg.user,
                            folder, mail_cfg.lookback_days)
    raise ValueError(f"unknown mailbox type {mail_cfg.type!r} (supported: imap, graph)")
