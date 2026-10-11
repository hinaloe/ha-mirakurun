# Mirakurun for Home Assistant

A Home Assistant custom integration for [Mirakurun](https://github.com/Chinachu/Mirakurun), the DVR tuner server for Japanese TV.
It shows tuner usage, server health and the program guide, and tells you when a new Mirakurun release is available.
It does not record or schedule recordings; use it alongside EPGStation for that.

## Features

- **Server**: tuners in use, free tuners, tuner streams, tuner respawns, error counters, whether the program guide is being gathered, and a Mirakurun update entity.
- **Tuners**: one device per tuner with its state (`free`, `in_use`, `disabled`, `fault`), the channel being received, the highest priority user, and a fault sensor. Tuners added later appear without restarting.
- **Broadcasts**: one device per broadcast of the selected types, with the current and next program, a calendar of the program guide, and a sensor that turns on while a subchannel airs a different program. Broadcasts added to or removed from Mirakurun are followed automatically; disable a broadcast's device to hide it.

### Multichannel broadcasts

Services on the same physical channel are grouped into broadcasts.
A subchannel that shares at least half of the main service's upcoming programs (for example NHK General 2) belongs to the main broadcast; its own programs show up in the calendar as `[service name] program` and turn on the "Subchannel airing a different program" sensor.
A subchannel that usually airs its own programs (for example TOKYO MX2) becomes a broadcast of its own.
The grouping is refreshed with the broadcast list (every 24 hours by default) and remembered across restarts. To keep borderline subchannels stable, a dependent subchannel only splits off below 40% shared programs, and an independent one only joins at 60% or more.

## Installation

1. In HACS, open the menu, choose **Custom repositories**, and add `https://github.com/hinaloe/ha-mirakurun` with the type **Integration**.
2. Install **Mirakurun** and restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration** and choose **Mirakurun**.

## Configuration

| Field | Description |
|---|---|
| URL | The Mirakurun server, for example `http://192.168.1.10:40772`. A trailing `/api` is accepted and removed. |

### Options

| Option | Default | Description |
|---|---|---|
| Broadcast types | Terrestrial (GR) | Types of broadcasts that get program guide entities. Only the types your Mirakurun has are offered (GR, BS, CS, SKY). |
| Tuner and status polling interval | 30 s (10–300 s) | How often tuner usage and server status are polled. |
| Program guide polling interval | 30 min (5–180 min) | How often programs are refreshed. Current and next programs switch exactly at program boundaries regardless of this interval. |
| Broadcast list refresh interval | 24 h (1–168 h) | How often the broadcast list is refreshed and subchannels are regrouped. |

Upgrading from a version with per-broadcast selection resets the broadcast types to Terrestrial (GR); select other types again in the options.

Home Assistant core integrations do not offer polling interval options.
This integration does, because Mirakurun runs on your local network and polling it is cheap.

The URL can be changed later with **Reconfigure**.

## Data updates

The integration polls Mirakurun's REST API: `/api/status` and `/api/tuners` at the status interval, `/api/programs` for broadcasts whose device is enabled at the program interval, `/api/services` plus the main service's programs of each physical channel of the selected types at the broadcast list interval (and once when the options open, to offer the types your server has), and `/api/version` every 12 hours.
Devices of tuners that no longer exist are cleaned up on the next reload or broadcast list refresh; you can also delete them manually from the device page.
It never opens a stream, so it does not occupy tuners or interfere with recordings.

## Examples

Entity IDs are generated from service names and differ between installations; replace them with the ones shown on your device pages.

Notify when a subchannel starts airing something different:

```yaml
automation:
  - triggers:
      - trigger: state
        entity_id: binary_sensor.nhk_general_1_tokyo_subchannel_airing_a_different_program
        to: "on"
    actions:
      - action: notify.mobile_app_phone
        data:
          message: >
            {{ state_attr(trigger.entity_id, 'subchannels')[0].service }}:
            {{ state_attr(trigger.entity_id, 'subchannels')[0].program }}
```

Do something when a program starts:

```yaml
automation:
  - triggers:
      - trigger: calendar
        event: start
        entity_id: calendar.tokyo_mx1_schedule
    conditions:
      - condition: template
        value_template: "{{ 'アニメ' in trigger.calendar_event.summary }}"
    actions:
      - action: light.turn_off
        target:
          area_id: living_room
```

## Supported versions

Tested with Mirakurun 4.x. Mirakurun 3.x is not tested.

## Known limitations

- Live streaming is not supported yet.
- Recording and reservations are out of scope; use EPGStation.
- Mirakurun has no authentication. Connecting through an authenticating reverse proxy is not supported.
- The update entity only reports new releases; it cannot install them.
- If Mirakurun cannot reach npm, the version request fails: the update entity becomes unavailable and is retried every 30 minutes. If Mirakurun returns no latest version, the latest version is shown as unknown. Everything else keeps working.

## Troubleshooting

- **Cannot connect**: open `http://<host>:40772/api/status` from the Home Assistant host. If it does not respond, check the address, port and firewall.
- **A broadcast is missing**: check that its type is selected in the options and that its device is not disabled. New broadcasts appear at the next broadcast list refresh; reload the integration to refresh now.
- **A subchannel is grouped the wrong way**: the grouping only changes when the share of simulcast programs clearly crosses the thresholds above. Reload the integration after the program guide has been updated.
- Download diagnostics from the integration page when reporting an issue.

## Removal

Go to **Settings → Devices & services → Mirakurun**, open the menu and choose **Delete**. Then remove the repository from HACS if you no longer need it.

## License

Apache License 2.0. See [LICENSE](LICENSE).
