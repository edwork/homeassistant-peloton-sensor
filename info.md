[Peloton Sensor](https://github.com/edwork/homeassistant-peloton-sensor) for homeassistant

This is a custom component to expose [Peloton](https://www.onepeloton.com/) workout data to [Homeassistant](https://home-assistant.io).

## Overview

- Sensor state shows either Complete or In Progress
- State Attributes include: Workout Type, Workout Title, Description, Duration, Rank, Work, Distance, Heart Rate, Resistance, Calories, Speed, Cadence, Power, and Instructor.

## Configuration
UI Configuration is in the works, but for now this requires YAML configuration of credentials. 
```
sensor:
  - platform: peloton
    username: thedude
    password: paSSw0rd
```

## Additional Sensors via Templating
Sometimes it's easier to work with the state directly, which will retain state history via the recorder. 
```
sensor:
  - platform: template
    sensors:
    power_output:
      friendly_name: "Power Output"
      value_template: >
        {{ states.sensor.peloton_edwork.attributes.Power }}
```

## Use Cases
- Automate lights and fans when you start or end a workout, or when your output exceeds a certain threshold. 
- Motovation - make HomeAssistant remind you to workout!
- Export your ride stats to InfluxDB via HomeAssistant

## Useful links

- [Community Discussion](https://community.home-assistant.io/t/peloton-support/72555/29)
