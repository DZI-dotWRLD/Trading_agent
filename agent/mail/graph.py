"""Microsoft 365 mailbox through Microsoft Graph (ADR-0002, docs/IMPLEMENTATION.md section 5b).

App-only access (client credentials) to ONE mailbox, with the application permissions Mail.Read and
Mail.Send, which VSCP's admin scopes to that mailbox. Same two methods as ``ImapSmtpMailbox``:

- ``fetch_new`` lists the inbox for the last ``lookback_days`` and downloads the file attachments of
  messages it hasn't seen. GET requests never change a message, so nothing is marked read, moved or deleted.
- ``send`` uses ``sendMail``. That request is limited to about 4 MB, and a bigger upload would need
  Mail.ReadWrite (drafts), so attachments that don't fit are left off with a note in the email instead.

Standard library only (urllib); ``http`` can be replaced in tests.
"""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Callable

from agent.mail.mailbox import Attachment, Email

API = "https://graph.microsoft.com/v1.0"
LOGIN = "https://login.microsoftonline.com"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_ATTACHMENT_BYTES = 2_800_000  # raw total; base64 adds a third, and sendMail refuses requests over ~4 MB

# (method, url, headers, body) -> (status, headers, body bytes)
Http = Callable[[str, str, dict, bytes | None], tuple[int, dict, bytes]]


class GraphError(Exception):
    pass


def _urllib(method: str, url: str, headers: dict, body: bytes | None) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read()


def _error(status: int, body: bytes) -> str:
    """Graph errors are {"error": {"code", "message"}}; sign-in errors are {"error", "error_description"}."""
    try:
        d = json.loads(body)
        err = d.get("error")
        code, msg = (err.get("code"), err.get("message")) if isinstance(err, dict) else (err, d.get("error_description"))
        return f"HTTP {status}: {code or ''} {msg or ''}".strip()
    except (ValueError, AttributeError):
        return f"HTTP {status}: {body[:200]!r}"


class GraphMailbox:
    def __init__(self, tenant_id: str, client_id: str, client_secret: str, mailbox: str,
                 folder: str = "inbox", lookback_days: int = 7, http: Http = _urllib):
        if not all((tenant_id, client_id, client_secret, mailbox)):
            raise ValueError("Graph mailbox needs a tenant id, client id, client secret and mailbox address")
        self.tenant_id, self.client_id, self.client_secret = tenant_id, client_id, client_secret
        self.mailbox, self.folder, self.lookback_days = mailbox, folder, lookback_days
        self.http = http
        self._token, self._expires = "", 0.0

    # ------------------------------------------------------------------ plumbing
    def _access_token(self) -> str:
        if self._token and time.monotonic() < self._expires:
            return self._token
        form = urllib.parse.urlencode({"client_id": self.client_id, "client_secret": self.client_secret,
                                       "scope": "https://graph.microsoft.com/.default",
                                       "grant_type": "client_credentials"}).encode()
        status, _, body = self.http("POST", f"{LOGIN}/{self.tenant_id}/oauth2/v2.0/token",
                                    {"Content-Type": "application/x-www-form-urlencoded"}, form)
        if status != 200:
            raise GraphError(f"Microsoft sign-in failed: {_error(status, body)}")
        tok = json.loads(body)
        self._token = tok["access_token"]
        self._expires = time.monotonic() + int(tok.get("expires_in", 3600)) - 300  # renew 5 minutes early
        return self._token

    def _call(self, method: str, url: str, payload: dict | None = None, raw: bool = False):
        url = url if url.startswith("https://") else API + url
        for retry in (True, False):
            headers = {"Authorization": f"Bearer {self._access_token()}"}
            body = None
            if payload is not None:
                headers["Content-Type"] = "application/json"
                body = json.dumps(payload).encode()
            status, resp_headers, data = self.http(method, url, headers, body)
            if status == 401 and retry:  # token revoked or expired early: sign in again once
                self._token = ""
                continue
            if status == 429 and retry:  # throttled: wait as told (capped), then once more
                time.sleep(min(int(resp_headers.get("Retry-After", 5)), 30))
                continue
            if status >= 400:
                raise GraphError(f"{method} {url.split('?')[0]} failed: {_error(status, data)}")
            return data if raw else (json.loads(data) if data else {})

    def _user(self) -> str:
        return f"/users/{urllib.parse.quote(self.mailbox)}"

    # ------------------------------------------------------------------ Mailbox
    def fetch_new(self, seen: set[str]) -> list[Email]:
        since = (datetime.now(timezone.utc) - timedelta(days=self.lookback_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        query = urllib.parse.urlencode({
            "$filter": f"receivedDateTime ge {since}",
            "$select": "id,internetMessageId,from,subject,receivedDateTime,hasAttachments",
            "$top": "50",
        })
        url: str | None = f"{self._user()}/mailFolders/{self.folder}/messages?{query}"
        out: list[Email] = []
        while url:
            page = self._call("GET", url)
            for m in page.get("value", []):
                mid = (m.get("internetMessageId") or "").strip() or m["id"]  # same key as IMAP's Message-ID
                if mid in seen:
                    continue
                received = m.get("receivedDateTime")
                out.append(Email(
                    message_id=mid,
                    sender=((m.get("from") or {}).get("emailAddress") or {}).get("address", "").lower(),
                    subject=m.get("subject") or "",
                    received=datetime.fromisoformat(received.replace("Z", "+00:00")) if received else None,
                    attachments=self._attachments(m["id"]) if m.get("hasAttachments") else [],
                ))
            url = page.get("@odata.nextLink")
        return out

    def _attachments(self, message_id: str) -> list[Attachment]:
        base = f"{self._user()}/messages/{urllib.parse.quote(message_id)}/attachments"
        listing = self._call("GET", f"{base}?$select=id,name,size")
        out = []
        for a in listing.get("value", []):
            # Only real files: an attached email (itemAttachment) or a OneDrive link (referenceAttachment) is skipped
            if a.get("@odata.type") != "#microsoft.graph.fileAttachment":
                continue
            data = self._call("GET", f"{base}/{urllib.parse.quote(a['id'])}/$value", raw=True)
            out.append(Attachment(a.get("name") or "", data))
        return out

    def send(self, to: list[str], subject: str, text: str, html: str | None = None,
             attachments: list[Attachment] = ()) -> None:
        attachments = list(attachments)
        if sum(len(a.data) for a in attachments) > MAX_ATTACHMENT_BYTES:
            names = ", ".join(a.filename for a in attachments)
            note = f"The attachment ({names}) is too large to email; open it from the dashboard's review queue."
            text = f"{note}\n\n{text}"
            html = f"<p><b>{note}</b></p>{html}" if html else None
            attachments = []
        message = {
            "subject": subject,
            "body": {"contentType": "HTML", "content": html} if html else {"contentType": "Text", "content": text},
            "toRecipients": [{"emailAddress": {"address": a}} for a in to],
            "attachments": [{"@odata.type": "#microsoft.graph.fileAttachment", "name": a.filename,
                             "contentType": XLSX, "contentBytes": base64.b64encode(a.data).decode()}
                            for a in attachments],
        }
        self._call("POST", f"{self._user()}/sendMail", {"message": message, "saveToSentItems": True}, raw=True)
