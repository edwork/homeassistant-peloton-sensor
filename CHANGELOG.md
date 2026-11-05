# Changelog

## Unreleased

### Fixes

- When Peloton rate limits the first request at startup, Home Assistant
  2026.11 and newer now wait for the time Peloton asks for before retrying
  the setup, as polling already did. Before, setup retried after its own
  shorter delay.

### Other

- The manifest declares how Home Assistant reaches Peloton (`connectivity`:
  cloud), a key added in Home Assistant 2026.11. Older versions ignore it.

## 1.1.0 (2026-11-03)

### New features

- A workout card for dashboards, Peloton workout, shows the workout in
  progress with live values and, between workouts, the latest workout. It
  loads automatically and needs no dashboard resource; see the README
  section "Workout card". It has a full and a compact variant, a card
  editor, and the Peloton logo and a Peloton Red border, which a theme can
  change.

### Fixes

- Total work, Total output, Total calories, Active calories and Stroke count
  could count a workout twice in long-term statistics. When a class
  completes, Peloton moves its start time forward past the countdown before
  the class (60 seconds on a recorded ride). 1.0.0 used the start time as the
  last reset, so Home Assistant started a new cycle and added the total
  again. The last reset is now the time the workout was created, which does
  not change. On the first start after the upgrade, the latest workout keeps
  the last reset already recorded for it, so it is not counted again.
  Sums recorded by 1.0.0 stay as they are; they can be corrected with the
  adjust button in Developer tools, Statistics.
- Total work stayed at 0 Wh during a workout, because Peloton fills in the
  workout's total work only when it completes. It now follows Total output
  during the workout, and Peloton's exact value replaces it at the end, which
  can be slightly lower.
- The manifest declares the integration's category (health and wellbeing),
  which the HACS validation asks for.

### Other

- Workout type values are shown with names in the Home Assistant UI, for
  example "Rowing" for `caesar`. Templates and automations still see the
  raw values.
- The integration now depends on Home Assistant's http integration, which
  serves the card.

## 1.0.0 (2026-10-21)

A rewrite of the integration. It now talks to Peloton with its own client,
stores tokens instead of the password, and makes one request per poll
between workouts.

### Breaking changes

- The configuration entry moves to version 3, which stores tokens instead of
  the password. Earlier versions cannot read it: to go back to 0.x, delete the
  Peloton entry and add the integration again after downgrading.
- Home Assistant 2026.3.1 or newer is required.
- Display names follow Home Assistant's entity naming: the entity name is
  shown after the device name "<first name> on Peloton", in sentence case
  without colons. For example "Jane on Peloton: Heart Rate: Average" is now
  "Heart rate average" on the device "Jane on Peloton". Entity ids, unique ids
  and history are unchanged.
- "Power Output" is now "Total work". It was always the workout's total work
  (energy, Wh), not power. Its entity id is unchanged. Power in watts is in the
  new Output sensors.
- The workout binary sensor's attributes are renamed to snake_case. Templates
  and automations that read them need updating:

  | Before | Now |
  | --- | --- |
  | `Workout Type` | `workout_type` |
  | `Device Type` | `device_type` |
  | `Ride Title` | `ride_title` |
  | `Ride Description` | `ride_description` |
  | `Workout Image` | `workout_image` |
  | `FTP` | `ftp` |
  | `Instructor` | `instructor` |
  | `Paused` | `paused` |

- Total output is an energy sensor in kJ (it was a measurement with the unit
  "kj"). Its existing long-term statistics are relabelled to kJ on the first
  start; the values do not change.
- Total work, Total output, Total calories and Active calories are totals
  that restart with each workout (state class `total` with the workout start
  as last reset), so their statistics count every workout. Total output,
  Total calories and Active calories were measurements before and have no
  recorded sums from earlier versions: charts of their change, such as
  "Output per week" in the example dashboard, start with the upgrade.
- Heart rate current is unknown between workouts and while a workout is
  paused, instead of 0. Cadence, resistance and speed current are still 0
  between workouts, and the new Output current is 0 too. While a workout is
  paused, these are also 0 instead of repeating the last sample.
- Distance and speed use the distance unit of the Peloton settings for every
  workout type. Rower distance, which Peloton reports in meters, was shown as
  kilometers or miles before. New installs show both in Home Assistant's unit
  system.

### Login and tokens

- The password is used once to get tokens and is not stored. On the first
  start after upgrading, the stored password is exchanged for tokens and then
  deleted. If Peloton rejects it, it is deleted at once and Home Assistant asks
  you to reauthenticate.
- The access token is renewed shortly before it expires, and once after a
  rejected request. Polls and restarts no longer log in.
- Reauthentication asks only for the password of the same account.
  Reconfiguration logs in again with a username and password for the same
  account.
- Deleting the entry revokes its refresh token with Peloton. Tokens replaced
  during reauthentication or reconfiguration are revoked too.
- Login errors are reported separately: wrong credentials, multi-factor
  authentication (not supported), rate limiting and connection errors.
- pylotoncycle is no longer used. The integration has no Python dependencies
  beyond Home Assistant.

### Polling

- Between workouts each poll is usually one request, every 15 seconds by
  default. Before, every poll made several requests every 10 seconds. A new
  workout can therefore take up to 15 seconds to show; set the interval
  between workouts to 10 seconds to keep the old timing. During a workout,
  details and live values are fetched every 10 seconds by default, as before.
  Both intervals can be changed in the options (#27).
- A workout that Peloton still reports as in progress after its class length
  plus 15 minutes, or after a configurable time for workouts without a class
  length (240 minutes by default), is treated as ended.
- Entities stay available for up to three failed polls in a row.
- Rate limits are respected: polling waits for Peloton's Retry-After, or backs
  off from one minute up to 15 minutes.

### New entities

- Output average, max and current, in W (#60).
- Total workouts, the number of workouts on the account (#46).
- Rower sensors: stroke rate average, max and current, split pace average,
  best and current, and stroke count. Tread sensors: pace average, best and
  current, incline average, max and current, and elevation. All are disabled
  by default (#105).

### Fixes

- An account without workouts can be set up. Before, setup failed and was
  retried indefinitely.
- Reauthentication works. Before, the reauthentication step could not be
  reached (#84).
- Speed max and current work on the Tread. Peloton sends tread speed only as
  an alternative of pace, which was not read before.
- Leaderboard total users is unknown, not 0, and the `ftp` attribute is
  empty, not 0, for workouts without a leaderboard or FTP (for example Just
  Ride).
- Units no longer change with Peloton's response, which raised repairs about
  changed units (#101).
- An unknown time zone on a workout no longer stops the update; times fall
  back to UTC.

### Examples

- New dashboard view and markdown card, using only built-in cards. The old
  example card, which no longer parsed, is removed (#50).
- New blueprint that turns a fan on during a workout and off a set time after
  it ends.

### Other

- Diagnostics download, with tokens and personal data removed.
- Releases are built by GitHub Actions and installed by HACS from
  `peloton.zip`.
- [docs/api.md](https://github.com/edwork/homeassistant-peloton-sensor/blob/master/docs/api.md) describes the Peloton endpoints the integration
  uses (#114).

## Earlier versions

Release notes for 0.12.1 and earlier are on the
[releases page](https://github.com/edwork/homeassistant-peloton-sensor/releases).
