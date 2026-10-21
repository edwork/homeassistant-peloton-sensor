# Peloton API notes

Peloton does not publish an API. This page describes the requests the
integration makes, as observed from Peloton's web app and in testing. Any of
it can change without notice. The client is in
[`custom_components/peloton/api/`](../custom_components/peloton/api/).

## Authentication

Peloton's login service is Auth0 at `https://auth.onepeloton.com`. The
integration uses the client id of Peloton's own web and iOS apps,
`mgsmWCD0A8Qn6uz6mmqI6qeBNHH9IPwS`. Peloton offers no way to register other
clients.

### Login (password grant)

```http
POST https://auth.onepeloton.com/oauth/token
Content-Type: application/json

{
  "grant_type": "password",
  "client_id": "mgsmWCD0A8Qn6uz6mmqI6qeBNHH9IPwS",
  "scope": "openid offline_access",
  "username": "<username or email>",
  "password": "<password>"
}
```

A successful response (HTTP 200) has `access_token`, `refresh_token`,
`id_token`, `expires_in` and `token_type: Bearer`. The access token is a JWT
that is valid for 48 hours. Its claims include:

- `exp`: expiry time (Unix seconds).
- `http://onepeloton.com/user_id`: the Peloton user id used in API paths.

The `offline_access` scope is what returns a refresh token.

The integration only logs in from the config flow (setup, reauthentication,
reconfiguration) and when it converts an entry from an earlier version that
stored the password. That conversion login is repeated at setup retries only
while Peloton cannot be reached or is rate limiting; after it succeeds the
password is removed, and a rejected password is deleted at once.

### Refresh

```http
POST https://auth.onepeloton.com/oauth/token
Content-Type: application/json

{
  "grant_type": "refresh_token",
  "client_id": "mgsmWCD0A8Qn6uz6mmqI6qeBNHH9IPwS",
  "refresh_token": "<refresh token>"
}
```

The response has a new `access_token` but no new `refresh_token`. The
original refresh token keeps working, so it is stored once and reused. The
integration refreshes 5 minutes before the access token expires, and once
when an API request returns HTTP 401.

### Revoke

```http
POST https://auth.onepeloton.com/oauth/revoke
Content-Type: application/json

{
  "client_id": "mgsmWCD0A8Qn6uz6mmqI6qeBNHH9IPwS",
  "token": "<refresh token>"
}
```

HTTP 200 means the refresh token is revoked. Access tokens already issued
stay valid until they expire. The integration revokes its refresh token when
the entry is deleted, and revokes tokens it replaces during reauthentication
or reconfiguration.

### Errors

| Response | Meaning |
| --- | --- |
| HTTP 403 with `"error": "invalid_grant"` | Wrong username or password, or a refresh token that is no longer valid. |
| `"error": "access_denied"` | Login refused. Treated like `invalid_grant`. |
| `"error": "mfa_required"` | Auth0's response for an account with multi-factor authentication. Not seen from Peloton so far; the integration reports that multi-factor login is not supported. |
| `"error": "unauthorized_client"` or `"invalid_client"` | Peloton no longer accepts this client id or grant. |
| HTTP 429, or a plain-text body `error code: 1015` | Rate limited (by Peloton or Cloudflare). Honour `Retry-After` if present. |
| HTTP 5xx | Server error; retry later. |

Peloton and Cloudflare rate limit logins per IP address. Repeated logins in a
short time, for example a login on every poll, lead to blocks of several
minutes.

## API requests

All API requests go to `https://api.onepeloton.com` with these headers:

```http
Authorization: Bearer <access token>
Accept: application/json
Peloton-Platform: web
```

`Peloton-Platform: web` is required by some endpoints (for example
`/api/user/{user_id}/overview`) and does no harm on the others.

### Endpoints the integration uses

| Request | Used for | When |
| --- | --- | --- |
| `GET /api/me` | Profile: `id`, `username`, `first_name`, `total_workouts`, `workout_counts` (list of `slug` and `count`). | At setup, hourly, and when the latest workout changes. |
| `GET /api/user/{user_id}/settings` | `distance_unit` (`imperial` or `metric`). | With `/api/me`. |
| `GET /api/user/{user_id}/workouts?sort_by=-created&page=0&limit=1&joins=ride,ride.instructor` | The latest workout, as the only element of `data` in a paginated response (`data` is empty for an account without workouts): `id`, `status`, `start_time`, `end_time`, `created_at`, `fitness_discipline`, `device_type`, `timezone`, and the class (`ride`) with its instructor. | Every poll. |
| `GET /api/workout/{workout_id}?joins=ride,ride.instructor` | The same fields plus `total_work` (joules), `leaderboard_rank`, `total_leaderboard_users`, `ftp_info.ftp` and `is_paused`. | During a workout, when the latest workout changes, and hourly. |
| `GET /api/workout/{workout_id}/performance_graph?every_n=50` | Totals and metrics, see below. | With the workout details. |

`status` is `IN_PROGRESS` while a workout runs and `COMPLETE` afterwards.
Times are Unix seconds. Peloton sometimes reports the same `start_time` and
`end_time`; the integration then uses the start time plus the class length.

Workouts without a class, such as Just Ride, have the ride id
`00000000000000000000000000000000`. Their `ride.instructor` is still present,
with a placeholder name such as `JUST RIDE` or `JUST RUN`, which the
integration does not show as an instructor. The
`ride,ride.instructor` joins embed the class and instructor in the workout,
so no separate instructor request is needed.

`fitness_discipline` is a slug: `cycling`, `bike_bootcamp`, `running`,
`walking`, `circuit` (tread bootcamp), `caesar` (rowing), `caesar_bootcamp`
(row bootcamp), `cardio`, `strength`, `yoga`, `stretching` and `meditation`.

### Performance graph

`every_n` is the sampling interval in seconds. The last sample is always
included, so a large `every_n` still gives the current value with a small
response.

- `summaries`: list of `slug`, `value` and `display_unit`. Slugs used:
  `total_output` (display unit `kj`, kilojoules), `distance`,
  `total_calories` or `calories` (kcal), `active_calories`, `stroke_count`
  (rower) and `elevation` (tread, `ft` or `m`).
- `average_summaries`: averages as Peloton displays them, for example
  `avg_speed`. For bike speed this is distance over time, which differs from
  the average of the samples.
- `metrics`: list of `slug`, `display_unit`, `average_value`, `max_value`
  and `values` (the samples). Slugs used: `output` (display unit `watts`),
  `cadence` (rpm), `resistance` (%), `speed`, `heart_rate` (bpm),
  `stroke_rate` (spm) and `split_pace` (`min/500m`) on the rower, and `pace`
  (`min/mi` or `min/km`) and `incline` (%) on the tread. Paces are decimal
  minutes, and their `max_value` is the fastest pace (the smallest number).
- On the tread, `speed` is not in `metrics` itself. It is in the
  `alternatives` list of the `pace` metric, with the same fields.

Distance and speed come in the workout's display unit (`mi` or `km`, `m`
for the rower, `mph` or `kph`). The rower also sends `caesar_metrics` and
`splits_metrics`, which the integration does not use.

### Other endpoints

These are known but not used by the integration:

- `GET /api/user/{user_id}/overview`: workout counts, personal records,
  streaks and achievements. Needs `Peloton-Platform: web`.
- `GET /api/instructor/{instructor_id}`: instructor details.
- Peloton's GraphQL gateway, which serves data such as the class stack, with
  the same access token.

## Trying it out

[`scripts/api_debug.py`](../scripts/api_debug.py) logs in once with the
integration's client, prints a summary of the account and the latest workout,
and revokes its refresh token before it exits. `--raw` prints the full
responses with usernames, email addresses and tokens redacted. The rest of the
personal data is printed as is, including names, ids, location, birthday and
body measurements, so do not post that output in public. `--fixtures DIR`
writes sanitized copies instead; review them before sharing. It reads the
credentials from `PELOTON_USERNAME` and `PELOTON_PASSWORD`, or prompts for
them.

Thanks to [ljhardy](https://github.com/ljhardy) for the endpoint notes in
[#114](https://github.com/edwork/homeassistant-peloton-sensor/issues/114).
