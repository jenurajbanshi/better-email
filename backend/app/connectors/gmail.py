"""Gmail connector scaffold.

Implements the same ``Connector`` interface as the mock. The OAuth flow and
Google API client are intentionally lazily imported and not wired into the
default runtime: the mock connector is the offline default. This file documents
the integration shape and least-privilege scopes so the real hookup is a
focused follow-up, not a redesign.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from email.utils import parseaddr, parsedate_to_datetime

from .base import Connector, NormalizedMessage

# Least-privilege: read messages + send replies only. Not full account access.
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


class GmailConnector(Connector):
    platform = "gmail"

    def __init__(self, *, client_id: str, client_secret: str, token: dict, owner_address: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token = token  # decrypted OAuth token dict (refresh handled by client)
        self.owner_address = owner_address.lower()
        self._creds = None
        self._service_obj = None

    def _service(self):
        if self._service_obj is not None:
            return self._service_obj
        try:
            from google.oauth2.credentials import Credentials  # lazy
            from googleapiclient.discovery import build
        except ImportError as e:  # pragma: no cover - optional dep
            raise RuntimeError(
                "Install google-api-python-client and google-auth to use the Gmail connector."
            ) from e
        self._creds = Credentials(
            token=self.token.get("access_token"),
            refresh_token=self.token.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self.client_id,
            client_secret=self.client_secret,
            scopes=GMAIL_SCOPES,
        )
        self._service_obj = build("gmail", "v1", credentials=self._creds, cache_discovery=False)
        return self._service_obj

    def export_token(self) -> dict | None:
        """Return the (possibly refreshed) token so callers can persist it.

        The Google client transparently refreshes the access token on expiry;
        we surface the new value here so the encrypted copy at rest stays
        current and the user never has to re-authorize.
        """
        creds = self._creds
        if creds is None:
            return None
        token = dict(self.token)
        if getattr(creds, "token", None):
            token["access_token"] = creds.token
        if getattr(creds, "refresh_token", None):
            token["refresh_token"] = creds.refresh_token
        expiry = getattr(creds, "expiry", None)
        if expiry is not None:
            token["expiry"] = expiry.isoformat()
        return token

    def fetch_messages(self, since: datetime | None = None) -> list[NormalizedMessage]:  # pragma: no cover - needs creds
        service = self._service()
        query = ""
        if since:
            query = f"after:{int(since.timestamp())}"
        result: list[NormalizedMessage] = []
        page_token: str | None = None
        # Paginate so a full mailbox (or a large incremental window) is captured,
        # not just the first 100 messages.
        while True:
            resp = (
                service.users()
                .messages()
                .list(userId="me", q=query, maxResults=100, pageToken=page_token)
                .execute()
            )
            for ref in resp.get("messages", []):
                full = service.users().messages().get(userId="me", id=ref["id"], format="full").execute()
                result.append(self._normalize(full))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return result

    def _normalize(self, msg: dict) -> NormalizedMessage:  # pragma: no cover - needs creds
        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
        from_name, from_email = parseaddr(headers.get("from", ""))
        label_ids = msg.get("labelIds", [])
        direction = "outbound" if "SENT" in label_ids else "inbound"
        try:
            received = parsedate_to_datetime(headers.get("date"))
        except (TypeError, ValueError):
            received = datetime.now(timezone.utc)
        return NormalizedMessage(
            platform=self.platform,
            platform_message_id=msg["id"],
            thread_id=msg.get("threadId"),
            direction=direction,
            received_at=received,
            from_name=from_name or None,
            from_email=(from_email or "").lower() or None,
            to_addrs=[a.strip() for a in headers.get("to", "").split(",") if a.strip()],
            subject=headers.get("subject"),
            body=self._extract_body(msg.get("payload", {})),
        )

    def _extract_body(self, payload: dict) -> str:  # pragma: no cover - needs creds
        if payload.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", "ignore")
        for part in payload.get("parts", []):
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", "ignore")
        for part in payload.get("parts", []):
            nested = self._extract_body(part)
            if nested:
                return nested
        return ""

    def send_reply(self, *, to, subject, body, thread_id=None) -> str:  # pragma: no cover - needs creds
        import email.message

        service = self._service()
        mime = email.message.EmailMessage()
        mime["To"] = ", ".join(to)
        mime["From"] = self.owner_address
        mime["Subject"] = subject
        mime.set_content(body)
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
        payload = {"raw": raw}
        if thread_id:
            payload["threadId"] = thread_id
        sent = service.users().messages().send(userId="me", body=payload).execute()
        return sent["id"]
