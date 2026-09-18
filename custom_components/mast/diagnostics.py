"""Diagnostics. The channel key is the whole credential, so it never appears."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import MastConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MastConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = entry.runtime_data
    return {
        "channel": data.client.target.redacted,
        "options": dict(entry.options),
        "heartbeat_running": data.cancel_heartbeat is not None,
        "open_pages": [
            {
                "state": page.state,
                "open_for": int(page.age),
                "has_dedupe_key": bool(page.dedupe_key),
                "waiters": len(page.waiters),
            }
            for page in data.watcher.open_pages
        ],
        "last_acked_by": data.watcher.last_acked_by,
        "last_open_for": data.watcher.last_open_for,
    }
