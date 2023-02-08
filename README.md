# Home Assistant Peloton Sensor

[![hacs_badge](https://img.shields.io/badge/HACS-Default-41BDF5.svg)](https://github.com/hacs/integration)
[![CodeQL Validation](https://github.com/edwork/homeassistant-peloton-sensor/actions/workflows/codeql-analysis.yml/badge.svg)](https://github.com/edwork/homeassistant-peloton-sensor/actions/workflows/codeql-analysis.yml)
[![Dependency Validation](https://github.com/edwork/homeassistant-peloton-sensor/actions/workflows/dependency-review.yml/badge.svg)](https://github.com/edwork/homeassistant-peloton-sensor/actions/workflows/dependency-review.yml)
[![HASSFest Validation](https://github.com/edwork/homeassistant-peloton-sensor/actions/workflows/hassfest.yml/badge.svg)](https://github.com/edwork/homeassistant-peloton-sensor/actions/workflows/hassfest.yml)

## Development & Community

This integration is developed and maintained by myself (edwork@) and a small group of contributors. We are not affiliated with Peloton. If you would like to show your support you're welcome to buy me a coffee!

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/edwork)

Please join our community discussion [here](https://community.home-assistant.io/t/peloton-support/72555) on the HomeAssistant Forms.

## Overview

HomeAssistant-Peloton-Sensor is an integration for [HomeAssistant](https://www.home-assistant.io/) that exposes your latest or current Peloton Workout session as a sensor. This can be useful to toggle lights, fans, or scenes according to your workout.

This integration creates one of the below sensors for each user. The "Workout" binary sensor registers itself as a device with all other sensors created as entities.

| Sensor Name              | Sensor Type             | Unit of Measurement | Attributes                                                                                      | Notes                                                         |
| ------------------------ | ----------------------- | ------------------- | ----------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| Workout                  | Binary Sensor (Running) | -                   | Workout Type, Device Type, Ride Title, Ride Description, Workout Image, FTP, Instructor, Paused | On/running when user is working out.                          |
| Cadence: Average         | Sensor                  | rpm                 |                                                                                                 |                                                               |
| Cadence: Max             | Sensor                  | rpm                 |                                                                                                 |                                                               |
| Calories                 | Sensor                  | kcal                |                                                                                                 |                                                               |
| Distance                 | Sensor                  | mi / k              |                                                                                                 | Uses unit of measurement specified in user's Peloton profile. |
| Duration                 | Sensor                  | min                 |                                                                                                 |                                                               |
| End Time                 | Sensor                  | -                   |                                                                                                 |                                                               |
| Start Time               | Sensor                  | -                   |                                                                                                 |                                                               |
| Heart Rate: Average      | Sensor                  | bpm                 |                                                                                                 |                                                               |
| Heart Rate: Max          | Sensor                  | bpm                 |                                                                                                 |                                                               |
| Leaderboard: Rank        | Sensor                  | -                   |                                                                                                 |                                                               |
| Leaderboard: Total Users | Sensor                  | -                   |                                                                                                 |                                                               |
| Power Output             | Sensor                  | Wh                  |                                                                                                 |                                                               |
| Resistance: Average      | Sensor                  | %                   |                                                                                                 |                                                               |
| Resistance: Max          | Sensor                  | %                   |                                                                                                 |                                                               |
| Speed: Average           | Sensor                  | mph / kph           |                                                                                                 | Uses unit of measurement specified in user's Peloton profile. |
| Speed: Max               | Sensor                  | mph / kph           |                                                                                                 | Uses unit of measurement specified in user's Peloton profile. |
| Workout count               | Sensor                  |            |                                                                                                 | `These sensors are disabled by default.` <br> Available types: <br>   - Bike Bootcamp <br>   - Cardio <br>   - Cycling <br>   - Meditation <br>   - Row Bootcamp <br>   - Rowing <br>   - Running <br>   - Strength <br>   - Stretching <br>   - Tread Bootcamp <br>   - Walking <br>   - Yoga|

## Under the Hood

This integration uses [Pylotoncycle](https://pypi.org/project/pylotoncycle/) to poll Peloton's API. Keep in mind that polling won't be instant when creating Automations.

## Integration Installation

### Using HACS (Recommended)

1. Search for and install "Peloton" in HACS.
2. Restart Home Assistant.
3. Set up the integration from your Home Assistant Integrations page.

### Manually Copy Files

1. Download this repository and place the `custom_components/peloton/` directory within `home_assistant_root/config/custom_components/`.
2. Restart Home Assistant.
3. Set up the integration from your Home Assistant Integrations page.

## Use Cases

- Automate lights and fans when you start or end a workout, or when your output exceeds a certain threshold.
- Motovation - make HomeAssistant remind you to workout!
- Export your ride stats to InfluxDB.

## To Do

- Expose more useful information by examining the entire JSON Object or other endpoints (PRs Welcome!)

## Final Thoughts

Please feel free to critique the code as well as submit feature requests or additions! The goal is to turn this into an award winning HomeAssistant Integration!
