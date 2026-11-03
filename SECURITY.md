# Security policy

## Supported versions

Fixes are made for the latest release only. Update to it before reporting a
problem.

## Reporting a vulnerability

Report vulnerabilities privately through GitHub: open the
[Security tab](https://github.com/edwork/homeassistant-peloton-sensor/security)
and choose Report a vulnerability. Do not open a public issue.

Include the integration and Home Assistant versions, the steps to reproduce
the problem and what an attacker could do with it.

Do not include your Peloton password, access or refresh tokens, or a log that
contains them. The diagnostics file from Settings > Devices & services >
Peloton has the tokens and the username removed and is safe to attach.

## Scope

In scope:

- The integration in `custom_components/peloton`, including its Peloton API
  client.
- The workout card in `frontend`.
- The release workflow and the `peloton.zip` attached to each release.

Out of scope:

- Peloton's own apps, website and API. Report those to Peloton.
- Home Assistant and HACS. Report those to their projects.

## How credentials are handled

The password is sent to Peloton once, at setup, reauthentication or
reconfiguration, and is not stored. The access and refresh tokens are stored
in the Home Assistant config entry. The integration does not write the
password or tokens to the log, and it revokes the refresh token when the entry
is deleted.

## What to expect

This project is maintained by one person in their spare time. Reports are
usually answered within a week. A confirmed problem is fixed in a new release,
and the advisory is published after that release.
