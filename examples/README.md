##  Markdown Template

An example markdown card, showing all available attributes.

The Current metrics section is only displayed when the bike is currently in use.

You will need to search/replace `FIRSTNAME` with your peloton profile's listed first name - as all sensors are prefixed with FIRSTNAME_on_peloton_SENSOR where firstname is given from your Peloton profile. 

## Preview

<!-- ![Preview](./assets/markdown_preview.jpg) -->

## Yaml (for Lovelace)

````
type: markdown
content: >-
{% if is_state('binary_sensor.FIRSTNAME_on_peloton_workout', 'on') %}
### Current Metrics:
| | | |
|:---|:---|---:| 
|<font color="firebrick"><ha-icon icon="mdi:heart-pulse"></ha-icon></font>| **Heart Rate (bpm):** | {{ states('sensor.FIRSTNAME_on_peloton_heart_rate_current') }} |
|<font color="darkorange"><ha-icon icon="mdi:omega"></ha-icon></font>| **Resistance (%):** | {{ states('sensor.FIRSTNAME_on_peloton_resistance_current') }} |
|<font color="darkorchid"><ha-icon icon="mdi:speedometer"></ha-icon></font>| **Speed (Mph):** | {{ states('sensor.FIRSTNAME_on_peloton_speed_current') }} |
|<font color="mediumseagreen"><ha-icon icon="mdi:sine-wave"></ha-icon></font>| **Cadence (Rpm):** | {{ states('sensor.FIRSTNAME_on_peloton_cadence_current') }} |
{% endif %}

 ### Latest Workout Summary:
<ha-icon icon="mdi:calendar-range"></ha-icon> **Date**: {{ states('sensor.FIRSTNAME_on_peloton_start_time') | as_timestamp | timestamp_custom("%m-%d-%Y")}}
<ha-icon icon="mdi:clock-in"></ha-icon> **start time**: {{ states('sensor.FIRSTNAME_on_peloton_start_time') | as_timestamp | timestamp_custom("%H:%M")}}
<ha-icon icon="mdi:clock-out"></ha-icon> **end time**: {{ states('sensor.FIRSTNAME_on_peloton_end_time') | as_timestamp | timestamp_custom("%H:%M") }} 
**Duration**: {{ states('sensor.FIRSTNAME_on_peloton_duration') }} min

{% if (state_attr('binary_sensor.FIRSTNAME_on_peloton_workout', 'Workout Image')|string != 'None') %}
   <img src="{{ state_attr('binary_sensor.FIRSTNAME_on_peloton_workout', 'Workout Image') }}">
{% endif %}

**{{ state_attr('binary_sensor.FIRSTNAME_on_peloton_workout', 'Ride Title') }} ({{ state_attr('binary_sensor.FIRSTNAME_on_peloton_workout', 'Workout Type') }})**
{{ state_attr('binary_sensor.FIRSTNAME_on_peloton_workout', 'Ride Description') }}
Instructor: {{ state_attr('binary_sensor.FIRSTNAME_on_peloton_workout', 'Instructor') }}

### Latest Workout Metrics:
| | | |
|:------------------------|:-------------------------------|------------------------------------------:| 
|<font color="royalblue"><ha-icon icon="mdi:map-marker-distance"></ha-icon></font>| **Distance (Mi):** | {{ states('sensor.FIRSTNAME_on_peloton_distance') | float | round(2) }} |
|<font color="firebrick"><ha-icon icon="mdi:heart-pulse"></ha-icon></font>| **Heart Rate (bpm):** | {{ states('sensor.FIRSTNAME_on_peloton_heart_rate_average') | float | round(0) }} avg / {{ states('sensor.FIRSTNAME_on_peloton_heart_rate_max')  | float | round(0) }} max
 |
|<font color="darkorange"><ha-icon icon="mdi:omega"></ha-icon></font>| **Resistance:** | {{ states('sensor.FIRSTNAME_on_peloton_resistance_average') | float | round(0) }}% avg / {{ states('sensor.FIRSTNAME_on_peloton_resistance_max') | float | round(0) }}% max
 |
|<font color="darkorchid"><ha-icon icon="mdi:speedometer"></ha-icon></font>| **Speed (Mph):** | {{ states('sensor.FIRSTNAME_on_peloton_speed_average')  | float | round(2) }}  avg / {{ states('sensor.FIRSTNAME_on_peloton_speed_max')  | float | round(2) }} max
 |
|<font color="mediumseagreen"><ha-icon icon="mdi:sine-wave"></ha-icon></font>| **Cadence (Rpm):** | {{ states('sensor.FIRSTNAME_on_peloton_cadence_average')  | float | round(0) }} avg / {{ states('sensor.FIRSTNAME_on_peloton_cadence_max')  | float | round(0) }} max
 |
|<font color="orangered"><ha-icon icon="mdi:lightning-bolt"></ha-icon></font>| **Power (W):** | {{ states('sensor.FIRSTNAME_on_peloton_power_output')  | float | round(2) }}
 |
 |<font color="orangered"><ha-icon icon="mdi:lightning-bolt"></ha-icon></font>| **Output (KJ):**  |  {{ states('sensor.FIRSTNAME_on_peloton_total_output')  | float | round(2) }}
 |
 |<font color="crimson"><ha-icon icon="mdi:food"></ha-icon></font>| **Calories (KCal):** | {{ states('sensor.FIRSTNAME_on_peloton_active_calories') }}
 |
 |<font color="yellowgreen"><ha-icon icon="mdi:chevron-triple-up"></ha-icon></font>| **Leaderboard Rank:**  | {% if states('sensor.FIRSTNAME_on_peloton_leaderboard_rank') != "None" -%}
{{ states('sensor.FIRSTNAME_on_peloton_leaderboard_rank') }} / {{ states('sensor.FIRSTNAME_on_peloton_leaderboard_total_users') }} ({{ 100 - (100 * (states('sensor.FIRSTNAME_on_peloton_leaderboard_rank') | int ) / (states('sensor.FIRSTNAME_on_peloton_leaderboard_total_users') | int)) | round(0) }}%)
{%- endif %}
 |
title: Peloton Card Template
````
