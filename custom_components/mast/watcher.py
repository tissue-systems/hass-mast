"""Watches open pages and reports the acknowledgement back into Home Assistant.

Mast stores a ``callback=`` URL on a message but does not fire it, so the only
way to learn that somebody answered is to ask. Asking costs requests against the
channel's 60-per-minute budget, which is shared with sends, so this module
spends at most half of it and drops to the slowest rung when several pages are
open at once.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
import logging
import time
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .api import MastClient, MastError, MastRateLimited
from .const import (
    EVENT_ACKNOWLEDGED,
    EVENT_EXPIRED,
    EVENT_RESOLVED,
    POLL_BUDGET_PER_MIN,
    POLL_LADDER,
    TERMINAL_STATES,
)

_LOGGER = logging.getLogger(__name__)

_TICK = 1.0

# A page nobody ever answers would otherwise be polled until Home Assistant
# restarts. Mast's own ceiling for `expire` is seven days; this is the cap for a
# page whose expiry we never managed to read.
_MAX_WATCH_SECS = 7 * 24 * 60 * 60


@dataclass(slots=True)
class OpenPage:
    """One page this instance sent and has not yet seen answered."""

    message_id: str
    title: str
    dedupe_key: str
    sent_at: float
    state: str = "queued"
    last_poll: float = 0.0
    expires_at: float | None = None
    waiters: list[asyncio.Future[dict[str, Any]]] = field(default_factory=list)

    @property
    def age(self) -> float:
        """Return how long this page has been open, in seconds."""
        return time.monotonic() - self.sent_at

    def due(self, now: float) -> bool:
        """Return whether this page is due for another poll."""
        for bound, every in POLL_LADDER:
            if bound is None or self.age < bound:
                return now - self.last_poll >= every
        return False


class MastWatcher:
    """Polls every open page on one channel until it reaches a terminal state."""

    def __init__(
        self, hass: HomeAssistant, client: MastClient, channel_name: str
    ) -> None:
        """Initialize the watcher."""
        self._hass = hass
        self._client = client
        self._channel = channel_name
        self._open: dict[str, OpenPage] = {}
        self._task: asyncio.Task[None] | None = None
        self._tokens = float(POLL_BUDGET_PER_MIN)
        self._refilled = time.monotonic()
        self._paused_until = 0.0
        self._listeners: list[Any] = []
        self.last_acked_by: str | None = None
        self.last_open_for: int | None = None

    def start(self) -> None:
        """Start the poll loop if it is not already running."""
        if self._task is None:
            self._task = self._hass.async_create_background_task(
                self._run(), name=f"mast watcher {self._channel}"
            )

    async def stop(self) -> None:
        """Stop polling and release anything waiting on an open page."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        # A pending gate must not hang a script through a reload.
        for page in list(self._open.values()):
            self._settle(page, timed_out=True)
        self._open.clear()

    @callback
    def async_add_listener(self, listener: Any) -> Any:
        """Register a callback fired whenever the open set or a state changes."""
        self._listeners.append(listener)

        def _remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _remove

    @property
    def open_pages(self) -> list[OpenPage]:
        """Return the pages still waiting for an answer."""
        return list(self._open.values())

    @property
    def has_open_page(self) -> bool:
        """Return whether any page is still waiting for an answer."""
        return bool(self._open)

    @callback
    def track(self, message_id: str, title: str, dedupe_key: str) -> OpenPage:
        """Start watching a page. Returns the existing record on a dedupe hit."""
        if (page := self._open.get(message_id)) is not None:
            return page
        page = OpenPage(
            message_id=message_id,
            title=title,
            dedupe_key=dedupe_key,
            sent_at=time.monotonic(),
        )
        self._open[message_id] = page
        self.start()
        self._notify()
        return page

    async def wait_for(self, page: OpenPage, timeout: float) -> dict[str, Any]:
        """Block until the page reaches a terminal state, or the timeout.

        A timeout is not a failure and does not stop the watch: the page stays
        open, and an acknowledgement arriving after the caller gave up still
        fires ``mast_acknowledged`` so an automation can act on it.
        """
        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[dict[str, Any]] = loop.create_future()
        page.waiters.append(waiter)
        try:
            return await asyncio.wait_for(asyncio.shield(waiter), timeout)
        except TimeoutError:
            return {
                "acknowledged": False,
                "timed_out": True,
                "state": page.state,
                "id": page.message_id,
            }
        finally:
            if waiter in page.waiters and waiter.done():
                page.waiters.remove(waiter)

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(_TICK)
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Catch broadly on purpose: one bad poll must not take the loop
                # down and leave every open page unwatched.
                _LOGGER.exception("Mast watcher tick failed for %s", self._channel)

    async def _tick(self) -> None:
        now = time.monotonic()
        if now < self._paused_until or not self._open:
            return
        self._refill(now)

        # Oldest first, so that when the budget runs short the page that has
        # been waiting longest is still the one being watched.
        due = sorted(
            (p for p in self._open.values() if p.due(now)), key=lambda p: p.sent_at
        )
        for page in due:
            if self._tokens < 1.0:
                return
            self._tokens -= 1.0
            page.last_poll = now
            await self._poll(page)

    def _refill(self, now: float) -> None:
        elapsed = now - self._refilled
        if elapsed <= 0:
            return
        self._refilled = now
        self._tokens = min(
            float(POLL_BUDGET_PER_MIN),
            self._tokens + elapsed * POLL_BUDGET_PER_MIN / 60.0,
        )

    async def _poll(self, page: OpenPage) -> None:
        try:
            record = await self._client.status(page.message_id)
        except MastRateLimited as err:
            # Back the whole channel off, not just this page: the limit is the
            # key's, and every other open page shares it.
            self._paused_until = time.monotonic() + err.retry_after
            return
        except MastError as err:
            _LOGGER.debug("Mast poll for %s failed: %s", page.message_id, err)
            return

        state = str(record.get("state") or page.state)
        changed = state != page.state
        page.state = state

        if page.age > _MAX_WATCH_SECS:
            self._settle(page, timed_out=True)
            return

        if state in TERMINAL_STATES:
            self._finish(page, record)
        elif changed:
            self._notify()

    def _finish(self, page: OpenPage, record: dict[str, Any]) -> None:
        acked_at = record.get("acked_at")
        acked_by = record.get("acked_by")
        open_for = _seconds_between(record.get("received_at"), acked_at)

        result = {
            "acknowledged": page.state == "acked",
            "timed_out": False,
            "state": page.state,
            "id": page.message_id,
            "acked_at": acked_at,
            "acked_by": acked_by,
            "open_for": open_for,
            "title": page.title,
            "key": page.dedupe_key,
        }

        event = {
            "acked": EVENT_ACKNOWLEDGED,
            "resolved": EVENT_RESOLVED,
            "expired": EVENT_EXPIRED,
        }.get(page.state)

        if page.state == "acked":
            self.last_acked_by = acked_by or None
            if open_for is not None:
                self.last_open_for = open_for

        if event is not None:
            self._hass.bus.async_fire(
                event,
                {
                    "channel": self._channel,
                    "message_id": page.message_id,
                    "title": page.title,
                    "key": page.dedupe_key,
                    "state": page.state,
                    "acked_at": acked_at,
                    "acked_by": acked_by,
                    "open_for": open_for,
                },
            )

        self._settle(page, result=result)

    def _settle(
        self,
        page: OpenPage,
        *,
        result: dict[str, Any] | None = None,
        timed_out: bool = False,
    ) -> None:
        self._open.pop(page.message_id, None)
        payload = result or {
            "acknowledged": False,
            "timed_out": timed_out,
            "state": page.state,
            "id": page.message_id,
        }
        for waiter in page.waiters:
            if not waiter.done():
                waiter.set_result(payload)
        page.waiters.clear()
        self._notify()

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()


def _seconds_between(start: Any, end: Any) -> int | None:
    """Whole seconds between two ISO-8601 stamps, or None if either is unusable.

    Mast omits rather than zeroes a duration it could not compute, and a reader
    has to treat absence as "unknown" rather than "instant".
    """
    if not start or not end:
        return None
    first = dt_util.parse_datetime(str(start))
    second = dt_util.parse_datetime(str(end))
    if first is None or second is None:
        return None
    return max(0, int((second - first).total_seconds()))
