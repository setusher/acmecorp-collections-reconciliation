"""Incoming mail via imaplib. Fetches UNSEEN messages without marking them; the
caller marks each one seen only after it has been stored, so a crash never loses mail."""
from __future__ import annotations

import asyncio
import imaplib
import logging
from typing import Protocol

from app.core.config import Settings

log = logging.getLogger(__name__)
MAX_PER_POLL = 50
MAX_MESSAGE_BYTES = 5 * 1024 * 1024


class InboxError(RuntimeError):
    pass


class InboxReader(Protocol):
    async def fetch_unseen(self) -> list[tuple[str, bytes]]: ...

    async def mark_seen(self, uids: list[str]) -> None: ...


class IMAPInbox:
    def __init__(self, settings: Settings):
        self.s = settings

    def _connect(self) -> imaplib.IMAP4:
        s = self.s
        conn = imaplib.IMAP4_SSL(s.imap_host, s.imap_port, timeout=30) if s.imap_ssl else imaplib.IMAP4(
            s.imap_host, s.imap_port, timeout=30)
        conn.login(s.imap_username, s.imap_password)
        conn.select(s.imap_folder)
        return conn

    def _fetch_sync(self) -> list[tuple[str, bytes]]:
        conn = self._connect()
        try:
            typ, data = conn.uid("search", None, "UNSEEN")
            if typ != "OK":
                raise InboxError("IMAP search failed")
            uids = [u.decode() for u in (data[0] or b"").split()][:MAX_PER_POLL]
            out: list[tuple[str, bytes]] = []
            for uid in uids:
                typ, msg_data = conn.uid("fetch", uid, "(BODY.PEEK[])")
                if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                    continue
                raw = msg_data[0][1]
                if len(raw) <= MAX_MESSAGE_BYTES:
                    out.append((uid, raw))
            return out
        finally:
            try:
                conn.logout()
            except (imaplib.IMAP4.error, OSError):
                pass

    def _mark_sync(self, uids: list[str]) -> None:
        if not uids:
            return
        conn = self._connect()
        try:
            conn.uid("store", ",".join(uids), "+FLAGS", "(\\Seen)")
        finally:
            try:
                conn.logout()
            except (imaplib.IMAP4.error, OSError):
                pass

    async def fetch_unseen(self) -> list[tuple[str, bytes]]:
        if not self.s.imap_configured:
            raise InboxError("IMAP is not configured (set IMAP_HOST, IMAP_USERNAME, IMAP_PASSWORD)")
        try:
            return await asyncio.to_thread(self._fetch_sync)
        except (imaplib.IMAP4.error, OSError) as exc:
            log.warning("IMAP fetch failed: %s", type(exc).__name__)
            raise InboxError(f"could not read inbox ({type(exc).__name__})") from exc

    async def mark_seen(self, uids: list[str]) -> None:
        try:
            await asyncio.to_thread(self._mark_sync, uids)
        except (imaplib.IMAP4.error, OSError) as exc:
            log.warning("IMAP mark-seen failed: %s", type(exc).__name__)


class FakeInbox:
    def __init__(self, messages: list[bytes] | None = None):
        self.messages: dict[str, bytes] = {}
        self.seen: set[str] = set()
        for m in messages or []:
            self.add(m)

    def add(self, raw: bytes) -> None:
        self.messages[str(len(self.messages) + 1)] = raw

    async def fetch_unseen(self) -> list[tuple[str, bytes]]:
        return [(u, r) for u, r in self.messages.items() if u not in self.seen]

    async def mark_seen(self, uids: list[str]) -> None:
        self.seen.update(uids)
