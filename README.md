# HomeAssistant Peloton Sensor

### Overview
HomeAssistant Peloton Sensor is an integration that exposes either your latest ride's stats or your current ride's stats as a sensor. This can be useful to turn off lights, turn on fans, set scenes, etc. 

### Under the Hood
This integration uses [Pylotoncycle](https://pypi.org/project/pylotoncycle/) to poll Peloton's API every minute. Keep in mind that polling won't be instant when creating Automations. 

### Custom Component Installation
Download this repository and place the `peloton/` directory within a folder called `custom_components/` within the root of your HomeAssistant Configuration directory.

### configuration.yaml
Your Configuration should look a little something like this:

```
sensor:
  - platform: peloton
    username: thedude
    password: paSSw0rd
```

This will give you a sensor named `sensor.peloton_USERNAME` - allowing for multiple instances!

### ToDo
* Configuration within the HA Web Interface (required for official HASS integration)
* HACS (working through the requirements right now)
* More Sensor Data

### Final Thoughts
Pull requests and issues are very welcome! At the moment the integration works but should be considered as beta. 

