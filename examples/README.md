# Examples

Ready-made dashboard cards and an automation for the Peloton integration.
They use only cards and features built into Home Assistant.

## Entity ids

Entity ids start with your Peloton first name followed by `_on_peloton_`, for
example `sensor.jane_on_peloton_cadence_current`. The examples use the
placeholder `name_on_peloton`; replace it with your prefix before you use them.
Settings > Devices & services > Peloton lists your entities.

Installs set up before version 1.0 keep their original entity ids. On those,
"Total work" is `sensor.<prefix>_power_output`.

## Dashboard view

[`dashboard.yaml`](dashboard.yaml) is a sections view with three columns:

- Workout: the workout sensor, and while a workout is in progress gauges for
  output, cadence and resistance plus heart rate and speed.
- Latest workout: class, instructor and time of the latest workout, and its
  totals and averages.
- History: workouts and output per week from long-term statistics, and the
  live values of the last three hours.

Gauges are hidden during workouts that have no value for them, such as
strength or yoga.

To add it, open a dashboard and choose Edit (on a dashboard that Home Assistant
still generates automatically, take control first). Add a view with +, open the
view dialog's three-dot menu, choose Edit in YAML, replace the contents with
this file and save. In the raw configuration editor the file goes under
`views:` as a list item: put `- ` before `title:` and indent the other lines
by two spaces.

## Markdown card

[`markdown_card.yaml`](markdown_card.yaml) is a single card with the latest
workout, and live values during a workout. Every value falls back to `-` when
it is unknown, and units come from the entities. Add it with Add card > Manual.

## Fan automation blueprint

[`workout_fan.yaml`](../blueprints/automation/peloton/workout_fan.yaml) turns a
fan, switch, light or input boolean on when a workout starts and off a set time
after it ends. Workout types can be excluded (meditation by default). If the
workout sensor becomes unavailable during a workout, the fan is turned off
after the same delay. Pick the fan entities directly; areas and devices are
not offered, because turning on a whole area would switch everything in it.

Import it from Settings > Automations & scenes > Blueprints > Import blueprint
with this URL:

```text
https://github.com/edwork/homeassistant-peloton-sensor/blob/master/blueprints/automation/peloton/workout_fan.yaml
```

The workout sensor is updated by polling, every 15 seconds between workouts
by default (configurable in the integration's options), so the fan starts
within that time of the workout starting. If Home Assistant restarts while
the off delay is running, the delay is lost and the fan stays on until the
next workout ends. A workout already running when Home Assistant starts does
not turn the fan on.

## Attributes of the workout sensor

The workout binary sensor has these attributes, which templates can read with
`state_attr()`: `workout_type`, `device_type`, `ride_title`,
`ride_description`, `workout_image`, `ftp`, `instructor` and `paused`.
Versions before 1.0 used Title Case names such as `Workout Type`.
