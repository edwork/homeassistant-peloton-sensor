"""A platform which allows you to get current and past ride data from Peloton."""

from datetime import timedelta
import logging, json, sys

import pylotoncycle
import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import (
    CONF_USERNAME,
    CONF_PASSWORD,
)
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import Entity
from homeassistant.util import Throttle

_LOGGER = logging.getLogger(__name__)

TIME_BETWEEN_UPDATES = timedelta(seconds=10)
CONF_HR_MONITOR = 'hr_monitor'
DEFAULT_HR_MONITOR = True

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Optional(CONF_HR_MONITOR, default=DEFAULT_HR_MONITOR): cv.boolean,
    }
)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Create the Peloton sensor."""

    pelo_user = config.get(CONF_USERNAME)
    pelo_pass = config.get(CONF_PASSWORD)
    pelo_hr_monitor = config.get(CONF_HR_MONITOR)

    session = async_get_clientsession(hass)

    sensor = [PelotonSensor(pelo_user, pelo_pass, pelo_hr_monitor)]

    async_add_entities(sensor, True)

class PelotonSensor(Entity):
    """Representation of a Peloton sensor."""

    def __init__(self, pelo_user, pelo_pass, pelo_hr_monitor):
        """Initialize the Peloton sensor."""
        self._state = None
        self._attributes = {}
        self.user = pelo_user
        self.password = pelo_pass

    @property
    def name(self):
        """Return the name of the sensor."""
        return ('Peloton ' + self.user)

    @property
    def icon(self):
        """Return the icon of the sensor."""
        if (self._state == 'COMPLETE'):
            return "mdi:bike"
        else:
            return "mdi:bike-fast"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def extra_state_attributes(self):
        """Return device specific state attributes."""
        return self._attributes

    def update(self):
        """Fetch new state data for the sensor."""

        # Fetch current state object
        _LOGGER.debug("Logging in and setting up session to the Peloton API")
        try:
            conn = pylotoncycle.PylotonCycle(self.user, self.password)
        except:
            _LOGGER.warning("Peloton Username or Password Incorrect")
        workouts = conn.GetRecentWorkouts(2)
        workout_latest = workouts[0]
        workout_latest_id = workout_latest["id"]
        stats_latest = conn.GetWorkoutMetricsById(workout_latest_id)

        _LOGGER.debug("Updating Primary State")
        # Update Primary State
        if (workout_latest["status"]== 'COMPLETE'):
            self._state = 'Complete'
        elif (workout_latest["status"]== 'IN_PROGRESS'):
            self._state = 'Active'
        else:
            self._state = workout_latest["UNKNOWN"]

        _LOGGER.debug("Updating Extra State Attributes")
        # Update Extra State Attributes
        try:
            self._attributes.update({"Workout Type":str(workout_latest["fitness_discipline"])})
            self._attributes.update({"Ride Title":str(workout_latest["ride"]["title"])})
            self._attributes.update({"Device Type":str(workout_latest["device_type"])})
            self._attributes.update({"Paused":str(workout_latest["is_paused"])})
            self._attributes.update({"Description":str(workout_latest["ride"]["description"])})
            self._attributes.update({"Start Time":str(workout_latest["start_time"])})
            self._attributes.update({"End Time":str(workout_latest["end_time"])})
            self._attributes.update({"FTP":str(workout_latest["ftp_info"]["ftp"])})
            self._attributes.update({"Duration Min":str((workout_latest["ride"]["duration"])//60)})
            self._attributes.update({"Leaderboard Rank":str(workout_latest["leaderboard_rank"])})
            self._attributes.update({"Leaderboard Users":str(workout_latest["total_leaderboard_users"])})
            self._attributes.update({"Output Kj":str((workout_latest["total_work"]//1000)+(workout_latest["total_work"]%1000>0))})
            self._attributes.update({"Distance Mi":str(stats_latest["summaries"][1]["value"])})
            self._attributes.update({"Calories KCal":str(int(stats_latest["summaries"][2]["value"]))})
            self._attributes.update({"Resistance Average %":str(stats_latest["metrics"][2]["average_value"])})
            self._attributes.update({"Resistance Max %":str(stats_latest["metrics"][2]["max_value"])})
            if stats_latest["metrics"][3]["display_unit"] == "kph":
                kph_multiplier = 1
                mph_multiplier = 0.60934
            else:
                kph_multiplier = 1.60934
                mph_multiplier = 1
            self._attributes.update({"Speed Average Mph":str(round(((stats_latest["metrics"][3]["average_value"])*mph_multiplier),2))})
            self._attributes.update({"Speed Max Mph":str(round(((stats_latest["metrics"][3]["max_value"])*mph_multiplier),2))})
            self._attributes.update({"Speed Average Kph":str(round(((stats_latest["metrics"][3]["average_value"])*kph_multiplier),2))})
            self._attributes.update({"Speed Max Kph":str(round(((stats_latest["metrics"][3]["max_value"])*kph_multiplier),2))})
            self._attributes.update({"Cadence Average Rpm":str(stats_latest["metrics"][1]["average_value"])})
            self._attributes.update({"Cadence Max Rpm":str(stats_latest["metrics"][1]["max_value"])})
            self._attributes.update({"Power Average W":str(stats_latest["metrics"][0]["average_value"])})
            self._attributes.update({"Power Max W":str(stats_latest["metrics"][0]["max_value"])})
            self._attributes.update({"Total Work":str(workout_latest["overall_summary"]["total_work"])})
            self._attributes.update({"Instructor":str(workout_latest["instructor_name"])})
            self._attributes.update({"Workout Image":str(workout_latest["ride"]["image_url"])})
            self._attributes.update({"Resistance %":str(stats_latest["metrics"][2]["average_value"])})
            # Need to see if these attributes show when a ride is in progress, or remove. 
            #self._attributes.update({"Speed Mph":str(workout_latest["overall_summary"]["speed"])})
            #self._attributes.update({"Speed Kph":str(round(((workout_latest["overall_summary"]["speed"])*1.60934),2))})
            #self._attributes.update({"Cadence Rpm":str(workout_latest["overall_summary"]["cadence"])})
            #self._attributes.update({"Power W":str(workout_latest["overall_summary"]["power"])})
        except:
            _LOGGER.warning("Error on parsing State Attributes, something in the API may have changed")
        
        # Check if HR Monitor is set to true in configuration
        if self.hr_monitor == True:
            # Update Heart Rate State Attributes if present
            try:
                self._attributes.update({"Heart Rate Average Bpm":str(stats_latest["metrics"][4]["average_value"])})
                self._attributes.update({"Heart Rate Max Bpm":str(stats_latest["metrics"][4]["max_value"])})
                self._attributes.update({"Heart Rate Bpm":str(stats_latest["metrics"][4]["average_value"])})
            except:
                _LOGGER.warning("Error on parsing State Attributes for Heart Rate functionality. It's possible that you do not have a heart rate monitor. You can disable the HR monitor in configuration by using the parameter 'hr_monitor: false'")
