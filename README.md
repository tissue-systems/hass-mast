# Mast for Home Assistant

[![Validate](https://github.com/tissue-systems/hass-mast/actions/workflows/validate.yml/badge.svg)](https://github.com/tissue-systems/hass-mast/actions/workflows/validate.yml)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)
[![License](https://img.shields.io/github/license/tissue-systems/hass-mast.svg)](LICENSE)

Home Assistant integration for [Mast](https://tissue.systems/mast), a pager app for the iPhone.

It adds a `mast.page` action that sends a message and then waits for a person to acknowledge it
before the automation carries on. That covers the automations a normal notification can't: a leak
sensor has gone wet and the main valve is about to close, a delivery is at the door and the lock is
about to open. The action returns whether anybody answered, which device answered, and how long
they took.

Home Assistant reads the acknowledgement by polling Mast on a connection it opened itself, so none
of this needs your instance to be reachable from the internet. The heartbeat runs the other way:
if Home Assistant stops checking in, Mast pages you, which is the one alarm your instance can't
raise for itself.

Mast is a one-time purchase, $4.99 in the US App Store. No subscription, no per-message charge.
iPhone, iOS 17.2 or later.

[![Download Mast Pager on the App Store](brand/app-store-badge.svg)](https://apps.apple.com/app/id6805232044?pt=129362925&ct=hass-readme&mt=8)

## Requirements

- Home Assistant 2025.8.0 or newer
- The Mast app, with at least one channel set up

## Installation

### HACS

Add this repository as a [custom repository](https://hacs.xyz/docs/faq/custom_repositories/) with
category **Integration**:

```text
https://github.com/tissue-systems/hass-mast
```

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=tissue-systems&repository=hass-mast&category=integration)

Download it, then restart Home Assistant.

### Manual

Copy `custom_components/mast` into `<config>/custom_components/mast`, where `<config>` is your
Home Assistant configuration directory, and restart.

## Setup

Go to **Settings** → **Devices & Services** → **Add Integration** → **Mast**, or use the button:

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=mast)

In the Mast app, open **Channels**, tap a channel and copy its URL. Paste it into the form.
Anything holding that URL can page the phone, so treat it like a password.

Setting up doesn't send a test page. The integration asks Mast about a message id that can't
exist, and the two different "not found" answers say whether the key resolves. Your phone stays
quiet.

Each channel becomes a device, and the name you give it is what the entity ids are built from.
Add the integration again for a second phone.

If you ever hit **Disconnect** in the Mast app, every channel key is re-minted. Use
**Reconfigure** on the integration and paste the new URL; entities and automations are unaffected.

### Options

Key | Default | Description
-|-|-
Heartbeat | off | Send a beat to this channel on a timer. Only useful on a channel set to Vital in the app.
Heartbeat interval | 5 min | How often to beat. Set the channel's grace period in the app a little longer than this.

## Actions

Action | Description
-|-
`mast.send` | Send a message at one of four priorities.
`mast.page` | Send at `page` priority and wait for somebody to acknowledge it.
`mast.resolve` | Close an open page because the condition cleared.
`mast.ping` | Send one heartbeat to a vital channel.
`mast.status` | Look up what happened to one message.

`mast.send` and `mast.page` take the same fields, except for the last four:

Field | Default | Description
-|-|-
`config_entry_id` | the only channel | Which channel to use. Needed once you have more than one.
`title` | | The line on the lock screen.
`body` | | The rest of the message. One of `title` or `body` is required.
`priority` | `normal`, or `page` for `mast.page` | `quiet`, `normal`, `loud` or `page`. Only `page` repeats and only `page` sounds with the ringer switch off.
`url` | | An `https` link the notification opens.
`url_title` | | The label on that link.
`key` | | Deduplication key. Messages sharing a key fold onto one card, and this is what `mast.resolve` closes.
`sound` | | Alert sound to use.
`retry` | | Seconds between re-alerts while a page goes unanswered.
`expire` | | Stop repeating after this many seconds, answered or not.
`ack` (`mast.send`) | `false` | Ask for an acknowledgement without waiting for it. The answer arrives as an event.
`silent` (`mast.send`) | `false` | Deliver without a sound, whatever the priority.
`wait_for_ack` (`mast.page`) | `true` | Hold the automation until somebody answers or the timeout passes.
`timeout` (`mast.page`) | `300` | Seconds to wait.

`mast.page` fills a `response_variable` with:

Field | Description
-|-
`id` | The Mast message id.
`state` | What Mast last said about the message.
`acknowledged` | `true` if somebody answered in time.
`timed_out` | `true` if the wait ran out. The page is still open on the phone.
`waited` | `false` when `wait_for_ack` was off, or when Mast suppressed the page (quiet hours, for instance) and so no answer was ever coming.
`acked_by` | The device that answered. Only present once somebody has.
`acked_at`, `open_for` | When it was answered, and how many seconds it was open. Mast measures `open_for`, so it doesn't depend on this machine's clock.

`mast.resolve` needs either a `key` or a `message_id`, and returns `open_for` for the incident it
closed. `mast.status` takes a `message_id` and returns Mast's record of it.

## Entities

Each channel gets these, named after the channel:

Entity | Description
-|-
`notify.<channel>` | The plain notify entity, for anything that just needs a line of text.
`binary_sensor.<channel>_page_open` | On while a page is waiting for an answer. Drive a siren off this directly; it goes off the moment somebody acknowledges.
`sensor.<channel>_open_pages` | How many pages are open.
`sensor.<channel>_last_acknowledged_by` | Which device answered last.
`sensor.<channel>_last_time_to_acknowledge` | Seconds the last page waited. It is a measurement, so long-term statistics keep the average time it takes your household to answer.
`event.<channel>_answer` | Fires on `acknowledged`, `resolved` and `expired`.

The same three also land on the bus as `mast_acknowledged`, `mast_resolved` and `mast_expired`,
carrying `channel`, `message_id`, `title`, `key`, `acked_by` and `open_for`.

## Blueprints

Four blueprints are in `blueprints/automation/mast/`. Import them with the buttons below, or copy
the files into `<config>/blueprints/automation/mast/`.

Blueprint | Description | |
-|-|-
Ask before acting | Page, wait, then run one set of actions if somebody answered and another if nobody did. | [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Ftissue-systems%2Fhass-mast%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fmast%2Fask-before-acting.yaml)
Act on silence | Page, and if nobody answers before the grace period runs out, do the safe thing anyway. | [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Ftissue-systems%2Fhass-mast%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fmast%2Fact-on-silence.yaml)
Water leak, page then close the valve | The worked example of the one above, wired to a moisture sensor and a valve. | [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Ftissue-systems%2Fhass-mast%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fmast%2Fleak-valve.yaml)
Vital heartbeat | Beat on a vital channel on a schedule, optionally only while some condition holds. | [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Ftissue-systems%2Fhass-mast%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fmast%2Fvital-heartbeat.yaml)

## Examples

### Ask before unlocking the door

```yaml
actions:
  - action: mast.page
    data:
      title: "Unlock the front door?"
      body: "A delivery is at the door and nobody is home."
      timeout: 120
    response_variable: answer
  - if: "{{ answer.acknowledged }}"
    then:
      - action: lock.unlock
        target: { entity_id: lock.front_door }
```

### Close the valve if nobody answers

Say in the body what happens if they don't answer. That is the part they read on the lock screen.

```yaml
actions:
  - action: mast.page
    data:
      title: "Water in the basement"
      body: "Closing the main valve in 2 minutes unless you acknowledge this."
      key: "leak-basement"
      priority: page
      retry: 30
      timeout: 120
    response_variable: answer
  - if: "{{ not answer.acknowledged }}"
    then:
      - action: switch.turn_off
        target: { entity_id: switch.main_valve }
```

### Let the house close the page

If the sensor clears while you're still driving home, `mast.resolve` turns the card on the phone
green and puts the incident duration on it, instead of sending a second notification saying never
mind.

```yaml
actions:
  - action: mast.resolve
    data:
      key: "leak-basement"
      title: "The basement is dry"
    response_variable: closed
```

`key` is what gives an incident an identity. Using `key: "{{ trigger.entity_id }}"` folds forty
re-triggers of one flapping sensor onto a single card with a count on it, and `mast.resolve`
closes that one card.

### Page when Home Assistant itself dies

Turn the heartbeat on in the integration's options and set the channel to **Vital** in the Mast
app, with a grace period a little longer than the interval. When the instance stops beating,
because the power went out or the SD card died or an upgrade went wrong, Mast pages you. No
automation running inside the house can do that.

## Notes

- A timeout is not a cancellation. `mast.page` returning `timed_out: true` leaves the page open on
  the phone. If somebody answers ten minutes later, `event.<channel>_answer` still fires and
  anything triggered off it still runs.
- There's no `mast.ack` action. An acknowledgement is supposed to mean a person looked at the page,
  and an action that let Home Assistant acknowledge by itself would defeat that. Use `mast.resolve`
  when the condition clears on its own.
- `url` has to be `https`. A `homeassistant://` deep link is rejected. Use a
  `https://my.home-assistant.io/redirect/entity/?entity_id=...` link instead: it passes the check,
  and it opens the companion app on the right screen.
- Mast allows 60 requests a minute per channel, shared between sends and the polling that reads
  acknowledgements. The integration spends at most half of that on polling, polls a page less often
  the longer it stays open, and when several are open at once keeps polling the oldest first.
- Diagnostics never carry the channel key. It is truncated to its first few characters there.

## Links

- [Mast](https://tissue.systems/mast) - the app, the four priority levels and vital channels.
- [Mast and Home Assistant](https://tissue.systems/docs/mast/home-assistant) - the same automations
  written with `rest_command`, if you'd rather not install a custom component.

## License

MIT, see [LICENSE](LICENSE).
