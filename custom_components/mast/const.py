"""Constants for the Mast integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "mast"

CONF_CHANNEL_URL: Final = "channel_url"
CONF_CHANNEL_NAME: Final = "channel_name"
CONF_HEARTBEAT: Final = "heartbeat"
CONF_HEARTBEAT_INTERVAL: Final = "heartbeat_interval"

DEFAULT_HOST: Final = "https://mast.tissue.dev"

# A channel key is "mk_" followed by 40 hex characters.
KEY_PREFIX: Final = "mk_"
KEY_HEX_LEN: Final = 40

# A message id is "mm_" followed by 32 hex characters.
MESSAGE_PREFIX: Final = "mm_"

PRIORITIES: Final = ["quiet", "normal", "loud", "page"]

# The server's own caps, so the integration refuses a send before spending a
# request on one that cannot be accepted (cell/manage/src/mast/ingest.rs).
MAX_TITLE_CHARS: Final = 250
MAX_BODY_CHARS: Final = 4096
MAX_URL_CHARS: Final = 512
MAX_DEDUPE_KEY_CHARS: Final = 120
MAX_REPEAT_SECS: Final = 86_400
MAX_EXPIRE_SECS: Final = 604_800

# 60 requests per minute per channel key, shared between sends and polls. Half
# the budget is reserved for sends, which is what the ladder in the watcher
# spends against.
RATE_LIMIT_PER_MIN: Final = 60
POLL_BUDGET_PER_MIN: Final = 30

# Age of an open page -> how often to poll it, seconds. Read in order; the first
# rung whose age bound is not yet passed wins.
POLL_LADDER: Final = ((30, 3), (300, 10), (None, 30))

# Terminal states: nothing more will happen to the message, so stop polling.
TERMINAL_STATES: Final = frozenset({"acked", "resolved", "expired"})

SERVICE_SEND: Final = "send"
SERVICE_PAGE: Final = "page"
SERVICE_RESOLVE: Final = "resolve"
SERVICE_PING: Final = "ping"
SERVICE_STATUS: Final = "status"

EVENT_ACKNOWLEDGED: Final = "mast_acknowledged"
EVENT_RESOLVED: Final = "mast_resolved"
EVENT_EXPIRED: Final = "mast_expired"

ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
ATTR_TITLE: Final = "title"
ATTR_BODY: Final = "body"
ATTR_PRIORITY: Final = "priority"
ATTR_URL: Final = "url"
ATTR_URL_TITLE: Final = "url_title"
ATTR_KEY: Final = "key"
ATTR_ACK: Final = "ack"
ATTR_SILENT: Final = "silent"
ATTR_RETRY: Final = "retry"
ATTR_EXPIRE: Final = "expire"
ATTR_SOUND: Final = "sound"
ATTR_MESSAGE_ID: Final = "message_id"
ATTR_WAIT_FOR_ACK: Final = "wait_for_ack"
ATTR_TIMEOUT: Final = "timeout"
