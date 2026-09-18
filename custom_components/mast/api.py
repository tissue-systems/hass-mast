"""HTTP client for a Mast channel.

Everything here works with the channel key alone: no Tissue account, no API
token, and nothing inbound. Most Home Assistant instances cannot be reached
from the internet, so the acknowledgement is polled for rather than pushed.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from typing import Any
from urllib.parse import urlsplit

import aiohttp

from .const import DEFAULT_HOST, KEY_HEX_LEN, KEY_PREFIX, MESSAGE_PREFIX

_LOGGER = logging.getLogger(__name__)

_KEY_RE = re.compile(rf"{KEY_PREFIX}[0-9a-f]{{{KEY_HEX_LEN}}}\Z")
_MESSAGE_RE = re.compile(rf"{MESSAGE_PREFIX}[0-9a-f]{{32}}\Z")

# Total time allowed for one request. The send path returns as soon as the
# message is stored, so anything slower than this is a network problem.
_TIMEOUT = aiohttp.ClientTimeout(total=15, connect=5)


class MastError(Exception):
    """Any failure talking to Mast."""


class MastUnknownChannel(MastError):
    """The key does not resolve: unknown, malformed, revoked or rotated away.

    Mast answers all four with the same 404 on purpose, so that a key cannot be
    probed. The integration cannot tell them apart either.
    """


class MastRateLimited(MastError):
    """Over the per-key or per-owner limit. Carries the server's Retry-After."""

    def __init__(self, retry_after: float = 1.0) -> None:
        """Initialize with the server's Retry-After."""
        super().__init__("Rate limited by Mast")
        self.retry_after = retry_after


class MastRejected(MastError):
    """The send was refused and the server named the field."""


def is_message_id(value: str) -> bool:
    """Whether a string has the shape of a Mast message id."""
    return bool(_MESSAGE_RE.match(value))


@dataclass(frozen=True, slots=True)
class ChannelTarget:
    """A channel URL split into the pieces every request is built from."""

    origin: str
    prefix: str
    key: str

    @property
    def send_url(self) -> str:
        """Return the URL a message is posted to."""
        return f"{self.origin}{self.prefix}/{self.key}"

    @property
    def fail_url(self) -> str:
        """Return the URL that declares a vital flatline."""
        return f"{self.send_url}/fail"

    def message_url(self, message_id: str) -> str:
        """Return the URL of one message's record."""
        return f"{self.send_url}/messages/{message_id}"

    @property
    def redacted(self) -> str:
        """The URL with the key masked, for logs and diagnostics."""
        return f"{self.origin}{self.prefix}/{self.key[:7]}…"


def parse_channel_url(raw: str) -> ChannelTarget:
    """Split a pasted channel URL, or a bare key, into a target.

    Accepts the canonical short form (``https://mast.tissue.dev/mk_...``), the
    explicit ingest path (``.../m/mk_...``) that the management API serves
    directly, and a bare key.
    """
    raw = raw.strip()
    if not raw:
        raise MastError("No channel URL given")

    if _KEY_RE.match(raw):
        return ChannelTarget(DEFAULT_HOST, "", raw)

    if "://" not in raw:
        raw = f"https://{raw}"

    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise MastError("The channel URL must be an http(s) URL")

    segments = [s for s in parts.path.split("/") if s]
    # mast.tissue.dev rewrites "/" onto "/m/", so both spellings reach the same
    # routes; keeping the one that was pasted avoids depending on the rewrite.
    prefix = ""
    if segments and segments[0] == "m":
        prefix = "/m"
        segments = segments[1:]

    if not segments:
        raise MastError("The channel URL has no key in it")

    key = segments[0]
    if not _KEY_RE.match(key):
        raise MastError(
            "That does not look like a channel key: expected 'mk_' and 40 hex characters"
        )

    origin = f"{parts.scheme}://{parts.netloc}"
    return ChannelTarget(origin, prefix, key)


class MastClient:
    """One channel's worth of Mast."""

    def __init__(self, session: aiohttp.ClientSession, target: ChannelTarget) -> None:
        """Initialize the client."""
        self._session = session
        self._target = target

    @property
    def target(self) -> ChannelTarget:
        """Return the channel this client talks to."""
        return self._target

    async def _request(
        self, method: str, url: str, *, data: dict[str, str] | None = None
    ) -> tuple[int, dict[str, Any]]:
        try:
            async with self._session.request(
                method, url, data=data, timeout=_TIMEOUT, allow_redirects=False
            ) as response:
                # Every Mast answer is one JSON line, but a proxy in front of a
                # self-hosted edge may not be, so a body that will not parse is
                # reported as the transport failure it is rather than crashing.
                try:
                    payload = await response.json(content_type=None)
                except (aiohttp.ContentTypeError, ValueError):
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}

                if response.status == 429:
                    raise MastRateLimited(
                        _retry_after(response.headers.get("Retry-After"))
                    )
                if response.status == 404:
                    raise MastUnknownChannel(_message(payload, "No such channel."))
                return response.status, payload
        except TimeoutError as err:
            raise MastError("Mast did not answer in time") from err
        except aiohttp.ClientError as err:
            raise MastError(f"Could not reach Mast: {err}") from err

    async def validate(self) -> None:
        """Prove the key resolves, without sending anything.

        ``GET /m/{key}/messages/{id}`` resolves the key before it looks at the
        message id, so an id that cannot be real separates the two 404s: an
        unusable key answers "No such channel." and a usable one answers "No
        such message." No message is stored and no phone is notified, which
        matters because this runs while somebody is filling in the config flow.
        """
        try:
            await self._request("GET", self._target.message_url("validate"))
        except MastUnknownChannel as err:
            if "No such message" in str(err):
                return
            raise
        # A 200 would mean "validate" was a real message id, which it cannot be.
        raise MastError(
            "Mast answered a key check in a way this version does not expect"
        )

    async def send(self, fields: dict[str, str]) -> dict[str, Any]:
        """Post one message. Answers the 202 body with the message id folded in."""
        status, payload = await self._request(
            "POST", self._target.send_url, data=fields
        )
        if status == 400:
            raise MastRejected(_message(payload, "Mast refused the send"))
        if status == 413:
            raise MastRejected("The message is over Mast's 16 KiB limit")
        if status >= 500:
            # A 502 does not prove nothing was stored: the failure can land on
            # either side of the durability line, so a blind retry can produce a
            # second page. Send with a dedupe key if a retry is wanted.
            raise MastError(_message(payload, f"Mast answered {status}"))
        return payload

    async def fail(self, fields: dict[str, str]) -> dict[str, Any]:
        """Declare a vital flatline without waiting for its period to lapse."""
        _, payload = await self._request("POST", self._target.fail_url, data=fields)
        return payload

    async def status(self, message_id: str) -> dict[str, Any]:
        """Read one message's lifecycle state, including the acknowledgement."""
        if not is_message_id(message_id):
            raise MastError(f"{message_id!r} is not a Mast message id")
        _, payload = await self._request("GET", self._target.message_url(message_id))
        return payload


def _message(payload: dict[str, Any], default: str) -> str:
    """The human half of an error body.

    The management API answers `{"error": {"code", "message"}}` uniformly, so
    the message is one level down. A flat body is read too, so that an
    unexpected shape does not turn into a wrong diagnosis.
    """
    error = payload.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return error["message"]
    if isinstance(error, str) and error:
        return error
    if isinstance(payload.get("message"), str):
        return payload["message"]
    return default


def _retry_after(header: str | None) -> float:
    """Seconds to wait, from the server's header, floored at one."""
    try:
        return max(1.0, float(header)) if header else 1.0
    except (TypeError, ValueError):
        return 1.0
