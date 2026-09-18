"""The Mast pager integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval

from .api import (
    MastClient,
    MastError,
    MastRejected,
    MastUnknownChannel,
    is_message_id,
    parse_channel_url,
)
from .const import (
    ATTR_ACK,
    ATTR_BODY,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_EXPIRE,
    ATTR_KEY,
    ATTR_MESSAGE_ID,
    ATTR_PRIORITY,
    ATTR_RETRY,
    ATTR_SILENT,
    ATTR_SOUND,
    ATTR_TIMEOUT,
    ATTR_TITLE,
    ATTR_URL,
    ATTR_URL_TITLE,
    ATTR_WAIT_FOR_ACK,
    CONF_CHANNEL_NAME,
    CONF_CHANNEL_URL,
    CONF_HEARTBEAT,
    CONF_HEARTBEAT_INTERVAL,
    DOMAIN,
    MAX_BODY_CHARS,
    MAX_DEDUPE_KEY_CHARS,
    MAX_EXPIRE_SECS,
    MAX_REPEAT_SECS,
    MAX_TITLE_CHARS,
    MAX_URL_CHARS,
    PRIORITIES,
    SERVICE_PAGE,
    SERVICE_PING,
    SERVICE_RESOLVE,
    SERVICE_SEND,
    SERVICE_STATUS,
)
from .watcher import MastWatcher

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.EVENT,
    Platform.NOTIFY,
    Platform.SENSOR,
]


@dataclass
class MastData:
    """What a configured channel carries at runtime."""

    client: MastClient
    watcher: MastWatcher
    channel_name: str
    cancel_heartbeat: Any = None


type MastConfigEntry = ConfigEntry[MastData]


_ENTRY = {
    vol.Optional(ATTR_CONFIG_ENTRY_ID): selector.ConfigEntrySelector(
        {"integration": DOMAIN}
    )
}

_SEND_FIELDS = {
    vol.Optional(ATTR_TITLE): vol.All(cv.string, vol.Length(max=MAX_TITLE_CHARS)),
    vol.Optional(ATTR_BODY): vol.All(cv.string, vol.Length(max=MAX_BODY_CHARS)),
    vol.Optional(ATTR_PRIORITY): vol.In(PRIORITIES),
    vol.Optional(ATTR_URL): vol.All(cv.string, vol.Length(max=MAX_URL_CHARS)),
    vol.Optional(ATTR_URL_TITLE): vol.All(cv.string, vol.Length(max=MAX_TITLE_CHARS)),
    vol.Optional(ATTR_KEY): vol.All(cv.string, vol.Length(max=MAX_DEDUPE_KEY_CHARS)),
    vol.Optional(ATTR_SOUND): cv.string,
    vol.Optional(ATTR_RETRY): vol.All(
        vol.Coerce(int), vol.Range(min=0, max=MAX_REPEAT_SECS)
    ),
    vol.Optional(ATTR_EXPIRE): vol.All(
        vol.Coerce(int), vol.Range(min=0, max=MAX_EXPIRE_SECS)
    ),
}

SEND_SCHEMA = vol.Schema(
    {
        **_ENTRY,
        **_SEND_FIELDS,
        vol.Optional(ATTR_ACK, default=False): cv.boolean,
        vol.Optional(ATTR_SILENT, default=False): cv.boolean,
    }
)

PAGE_SCHEMA = vol.Schema(
    {
        **_ENTRY,
        **_SEND_FIELDS,
        vol.Optional(ATTR_WAIT_FOR_ACK, default=True): cv.boolean,
        vol.Optional(ATTR_TIMEOUT, default=300): vol.All(
            vol.Coerce(float), vol.Range(min=1, max=86_400)
        ),
    }
)

RESOLVE_SCHEMA = vol.Schema(
    {
        **_ENTRY,
        vol.Optional(ATTR_KEY): vol.All(
            cv.string, vol.Length(max=MAX_DEDUPE_KEY_CHARS)
        ),
        vol.Optional(ATTR_MESSAGE_ID): cv.string,
        vol.Optional(ATTR_TITLE): vol.All(cv.string, vol.Length(max=MAX_TITLE_CHARS)),
        vol.Optional(ATTR_BODY): vol.All(cv.string, vol.Length(max=MAX_BODY_CHARS)),
    }
)

PING_SCHEMA = vol.Schema({**_ENTRY, vol.Optional(ATTR_BODY): cv.string})

STATUS_SCHEMA = vol.Schema({**_ENTRY, vol.Required(ATTR_MESSAGE_ID): cv.string})


async def async_setup_entry(hass: HomeAssistant, entry: MastConfigEntry) -> bool:
    """Set up one Mast channel."""
    try:
        target = parse_channel_url(entry.data[CONF_CHANNEL_URL])
    except MastError as err:
        raise HomeAssistantError(str(err)) from err

    client = MastClient(async_get_clientsession(hass), target)
    channel_name = entry.data.get(CONF_CHANNEL_NAME) or entry.title
    watcher = MastWatcher(hass, client, channel_name)
    entry.runtime_data = MastData(client, watcher, channel_name)

    if entry.options.get(CONF_HEARTBEAT, entry.data.get(CONF_HEARTBEAT, False)):
        minutes = int(
            entry.options.get(
                CONF_HEARTBEAT_INTERVAL, entry.data.get(CONF_HEARTBEAT_INTERVAL, 5)
            )
        )
        entry.runtime_data.cancel_heartbeat = async_track_time_interval(
            hass,
            _make_heartbeat(entry),
            timedelta(minutes=minutes),
            name=f"mast heartbeat {channel_name}",
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MastConfigEntry) -> bool:
    """Tear one channel down."""
    data = entry.runtime_data
    if data.cancel_heartbeat is not None:
        data.cancel_heartbeat()
    await data.watcher.stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _make_heartbeat(entry: MastConfigEntry):
    """A beat on a vitals channel: Mast pages when these stop arriving."""

    async def _beat(_now: Any) -> None:
        try:
            await entry.runtime_data.client.send({})
        except MastError as err:
            # A missed beat is not worth an error in the log every period.
            # Mast raises the flatline page, which is the actual alarm.
            _LOGGER.debug("Mast heartbeat failed: %s", err)

    return _beat


def _resolve_entry(hass: HomeAssistant, call: ServiceCall) -> MastConfigEntry:
    """Pick the channel a call is for, defaulting to the only one configured."""
    entries = [
        entry
        for entry in hass.config_entries.async_loaded_entries(DOMAIN)
        if hasattr(entry, "runtime_data")
    ]
    if entry_id := call.data.get(ATTR_CONFIG_ENTRY_ID):
        for entry in entries:
            if entry.entry_id == entry_id:
                return entry
        raise ServiceValidationError(f"No loaded Mast channel with id {entry_id}")
    if not entries:
        raise ServiceValidationError("No Mast channel is configured")
    if len(entries) > 1:
        raise ServiceValidationError(
            "More than one Mast channel is configured; name one with config_entry_id"
        )
    return entries[0]


def _fields(
    call: ServiceCall, *, extra: dict[str, str] | None = None
) -> dict[str, str]:
    """Turn service data into the form fields Mast's ingest takes."""
    out: dict[str, str] = {}
    for attr in (
        ATTR_TITLE,
        ATTR_BODY,
        ATTR_PRIORITY,
        ATTR_URL,
        ATTR_URL_TITLE,
        ATTR_KEY,
        ATTR_SOUND,
    ):
        if (value := call.data.get(attr)) not in (None, ""):
            out[attr] = str(value)
    for attr in (ATTR_RETRY, ATTR_EXPIRE):
        if (value := call.data.get(attr)) is not None:
            out[attr] = str(int(value))
    if call.data.get(ATTR_ACK):
        out["ack"] = "required"
    if call.data.get(ATTR_SILENT):
        out["silent"] = "1"
    if extra:
        out.update(extra)
    if not out.get(ATTR_TITLE) and not out.get(ATTR_BODY):
        raise ServiceValidationError("A Mast message needs a title or a body")
    return out


def _translate(err: MastError) -> HomeAssistantError:
    if isinstance(err, MastUnknownChannel):
        return HomeAssistantError(
            "Mast does not know this channel key. It may have been revoked or rotated."
        )
    if isinstance(err, MastRejected):
        return ServiceValidationError(str(err))
    return HomeAssistantError(str(err))


def _async_register_services(hass: HomeAssistant) -> None:
    """Register the Mast actions once, however many channels are configured."""
    if hass.services.has_service(DOMAIN, SERVICE_SEND):
        return

    async def _send(call: ServiceCall) -> ServiceResponse:
        entry = _resolve_entry(hass, call)
        try:
            answer = await entry.runtime_data.client.send(_fields(call))
        except MastError as err:
            raise _translate(err) from err
        message_id = answer.get("id")
        if call.data.get(ATTR_ACK) and message_id:
            entry.runtime_data.watcher.track(
                message_id, call.data.get(ATTR_TITLE, ""), call.data.get(ATTR_KEY, "")
            )
        return {
            "id": message_id,
            "state": answer.get("state"),
            "duplicate": bool(answer.get("duplicate")),
        }

    async def _page(call: ServiceCall) -> ServiceResponse:
        entry = _resolve_entry(hass, call)
        data = entry.runtime_data
        fields = _fields(call, extra={"ack": "required"})
        fields.setdefault(ATTR_PRIORITY, "page")
        try:
            answer = await data.client.send(fields)
        except MastError as err:
            raise _translate(err) from err

        message_id = answer.get("id")
        state = answer.get("state")
        if not message_id or state in ("muted", "suppressed"):
            # Mast suppressed the message, so nobody was interrupted and no
            # acknowledgement is coming. There is nothing to wait for.
            return {
                "id": message_id,
                "state": state,
                "acknowledged": False,
                "timed_out": False,
                "waited": False,
            }

        page = data.watcher.track(
            message_id, fields.get(ATTR_TITLE, ""), fields.get(ATTR_KEY, "")
        )
        if not call.data.get(ATTR_WAIT_FOR_ACK, True):
            return {
                "id": message_id,
                "state": state,
                "acknowledged": False,
                "timed_out": False,
                "waited": False,
            }

        result = await data.watcher.wait_for(page, float(call.data[ATTR_TIMEOUT]))
        return {**result, "waited": True}

    async def _resolve(call: ServiceCall) -> ServiceResponse:
        entry = _resolve_entry(hass, call)
        message_id = call.data.get(ATTR_MESSAGE_ID)
        dedupe_key = call.data.get(ATTR_KEY)
        if not message_id and not dedupe_key:
            raise ServiceValidationError(
                "Closing a page needs either a key or a message_id"
            )
        if message_id and not is_message_id(message_id):
            raise ServiceValidationError(f"{message_id!r} is not a Mast message id")

        fields: dict[str, str] = {
            "resolve": message_id or "1",
            ATTR_BODY: call.data.get(ATTR_BODY) or "Resolved by Home Assistant",
        }
        if dedupe_key:
            fields[ATTR_KEY] = dedupe_key
        if title := call.data.get(ATTR_TITLE):
            fields[ATTR_TITLE] = title
        try:
            answer = await entry.runtime_data.client.send(fields)
        except MastError as err:
            raise _translate(err) from err
        return {
            "id": answer.get("id"),
            "state": answer.get("state"),
            "open_for": answer.get("open_for"),
        }

    async def _ping(call: ServiceCall) -> ServiceResponse:
        entry = _resolve_entry(hass, call)
        fields = {ATTR_BODY: call.data[ATTR_BODY]} if call.data.get(ATTR_BODY) else {}
        try:
            answer = await entry.runtime_data.client.send(fields)
        except MastError as err:
            raise _translate(err) from err
        return {"state": answer.get("state"), "open_for": answer.get("open_for")}

    async def _status(call: ServiceCall) -> ServiceResponse:
        entry = _resolve_entry(hass, call)
        if not is_message_id(call.data[ATTR_MESSAGE_ID]):
            raise ServiceValidationError(
                f"{call.data[ATTR_MESSAGE_ID]!r} is not a Mast message id"
            )
        try:
            return dict(
                await entry.runtime_data.client.status(call.data[ATTR_MESSAGE_ID])
            )
        except MastError as err:
            raise _translate(err) from err

    for name, handler, schema in (
        (SERVICE_SEND, _send, SEND_SCHEMA),
        (SERVICE_PAGE, _page, PAGE_SCHEMA),
        (SERVICE_RESOLVE, _resolve, RESOLVE_SCHEMA),
        (SERVICE_PING, _ping, PING_SCHEMA),
        (SERVICE_STATUS, _status, STATUS_SCHEMA),
    ):
        hass.services.async_register(
            DOMAIN,
            name,
            handler,
            schema=schema,
            supports_response=SupportsResponse.OPTIONAL,
        )
