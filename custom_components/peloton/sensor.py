"""A platform which allows you to get current and past ride data from Peloton."""

from datetime import datetime, timedelta
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

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
    }
)

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Create the Peloton sensor."""

    pelo_user = config.get(CONF_USERNAME)
    pelo_pass = config.get(CONF_PASSWORD)

    session = async_get_clientsession(hass)

    sensor = [PelotonSensor(pelo_user, pelo_pass)]

    async_add_entities(sensor, True)

class PelotonSensor(Entity):
    """Representation of a Peloton sensor."""

    def __init__(self, pelo_user, pelo_pass):
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
            self._state = 'Unavailable'

        #Update Extra State Attributes
        _LOGGER.debug("Updating Extra State Attributes")
        try:
            self._attributes.update({"Workout Type":str(workout_latest["fitness_discipline"])})
        except:
            self._attributes.update({"Workout Type":str("Unavailable")})
            _LOGGER.debug("Error Updating Peloton Attribute - Workout Type")
        try:
            self._attributes.update({"Ride Title":str(workout_latest["ride"]["title"])})
        except:
            self._attributes.update({"Ride Title":str("Unavailable")})
            _LOGGER.debug("Error Updating Peloton Attribute - Ride Title")
        try:
            self._attributes.update({"Device Type":str(workout_latest["device_type"])})
        except:
            self._attributes.update({"Device Type":str("Unavailable")})
            _LOGGER.debug("Error Updating Peloton Attribute - Device Type")
        try:
            self._attributes.update({"Paused":str(workout_latest["is_paused"])})
        except:
            self._attributes.update({"Paused":str(Unavailable)})
            _LOGGER.debug("Error Updating Peloton Attribute - Paused")
        try:
            self._attributes.update({"Description":str(workout_latest["ride"]["description"])})
        except:
            self._attributes.update({"Description":str("Unavailable")})
            _LOGGER.debug("Error Updating Peloton Attribute - Description")
        try:
            self._attributes.update({"Start Time":str(datetime.fromtimestamp(workout_latest["start_time"]))})
        except:
            self._attributes.update({"Start Time":str("Unavailable")})
            _LOGGER.debug("Error Updating Peloton Attribute - Start Time")
        try:
            self._attributes.update({"End Time":str(datetime.fromtimestamp(workout_latest["end_time"]))})
        except:
            self._attributes.update({"End Time":str(Unavailable)})
            _LOGGER.debug("Error Updating Peloton Attribute - End Time")
        try:
            self._attributes.update({"FTP":str(workout_latest["ftp_info"]["ftp"])})
        except:
            self._attributes.update({"FTP":str("Unavailable")})
            _LOGGER.debug("Error Updating Peloton Attribute - FTP")
        try:
            self._attributes.update({"Duration Min":str((workout_latest["ride"]["duration"])//60)})
        except:
            self._attributes.update({"Duration Min":str("Unavailable")})
            _LOGGER.debug("Error Updating Peloton Attribute - Duration Min")
        try:
            self._attributes.update({"Leaderboard Rank":str(workout_latest["leaderboard_rank"])})
        except:
            self._attributes.update({"Leaderboard Rank":str("Unavailable")})
            _LOGGER.debug("Error Updating Peloton Attribute - Leaderboard Rank")
        try:
            self._attributes.update({"Leaderboard Users":str(workout_latest["total_leaderboard_users"])})
        except:
            self._attributes.update({"Leaderboard Users":str("Unavailable")})
            _LOGGER.debug("Error Updating Peloton Attribute - Leaderboard Users")
        try:
            self._attributes.update({"Output Kj":str((workout_latest["total_work"]//1000)+(workout_latest["total_work"]%1000>0))})
        except:
            self._attributes.update({"Output Kj":str("Unavailable")})
            _LOGGER.debug("Error Updating Peloton Attribute - Output Kj")
        try:
            self._attributes.update({"Distance Mi":str(stats_latest["summaries"][1]["value"])})
        except:
            self._attributes.update({"Distance Mi":str("Unavailable")})
            _LOGGER.debug("Error Updating Peloton Attribute - Distance Mi")
        try:
            self._attributes.update({"Calories KCal":str(int(stats_latest["summaries"][2]["value"]))})
        except:
            self._attributes.update({"Calories KCal":str("Unavailable")})
            _LOGGER.debug("Error Updating Peloton Attribute - Calories KCal")
        try:
            self._attributes.update({"Heart Rate Average Bpm":str(stats_latest["metrics"][4]["average_value"])})
        except:
            self._attributes.update({"Heart Rate Average Bpm":str("Unavailable")})
            _LOGGER.debug("Error Updating Peloton Attribute - Heart Rate Average Bpm")
        try:
            self._attributes.update({"Heart Rate Max Bpm":str(stats_latest["metrics"][4]["max_value"])})
        except:
            self._attributes.update({"Heart Rate Max Bpm":str("Unavailable")})
            _LOGGER.debug("Error Updating Peloton Attribute - Heart Rate Max Bpm")
        try:
            self._attributes.update({"Heart Rate Bpm":str(stats_latest["metrics"][4]["average_value"])})
        except:
            self._attributes.update({"Heart Rate Bpm":str("Unavailable")})
            _LOGGER.debug("Error Updating Peloton Attribute - Heart Rate Bpm")
        try:
            self._attributes.update({"Resistance Average %":str(stats_latest["metrics"][2]["average_value"])})
        except:
            self._attributes.update({"Resistance Average %":str("Unavailable")})
            _LOGGER.debug("Error Updating Peloton Attribute - Resistance Average")
        try:
            self._attributes.update({"Resistance Max %":str(stats_latest["metrics"][2]["max_value"])})
        except:
            self._attributes.update({"Resistance Max %":str("Unavailable")})
            _LOGGER.debug("Error Updating Peloton Attribute - Resistance Max Percentage")
        try:
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
        except:
            self._attributes.update({"Speed Average Mph":str("Unavailable")})
            self._attributes.update({"Speed Max Mph":str("Unavailable")})
            self._attributes.update({"Speed Average Kph":str("Unavailable")})
            self._attributes.update({"Speed Max Kph":str("Unavailable")})
            _LOGGER.debug("Error Updating Peloton Attribute - Speed Average and Max Speeds")
        try:
            self._attributes.update({"Cadence Average Rpm":str(stats_latest["metrics"][1]["average_value"])})
        except:
            self._attributes.update({"Cadence Average Rpm":str("Unavailable")})
            _LOGGER.debug("Error Updating Peloton Attribute - Cadence Average Rpm")
        try:
            self._attributes.update({"Cadence Max Rpm":str(stats_latest["metrics"][1]["max_value"])})
        except:
            self._attributes.update({"Cadence Max Rpm":str("Unavailable")})
            _LOGGER.debug("Error Updating Peloton Attribute - Cadence Max Rpm")
        try:
            self._attributes.update({"Power Average W":str(stats_latest["metrics"][0]["average_value"])})
        except:
            self._attributes.update({"Power Average W":str("Unavailable")})
            _LOGGER.debug("Error Updating Peloton Attribute - Power Average W")
        try:
            self._attributes.update({"Power Max W":str(stats_latest["metrics"][0]["max_value"])})
        except:
            self._attributes.update({"Power Max W":str("Unavailable")})
            _LOGGER.debug("Error Updating Peloton Attribute - Power Max W")
        try:
            self._attributes.update({"Total Work":str(workout_latest["overall_summary"]["total_work"])})
        except:
            self._attributes.update({"Total Work":str("Unavailable")})
            _LOGGER.debug("Error Updating Peloton Attribute - Total Work")
        try:
            self._attributes.update({"Instructor":str(workout_latest["instructor_name"])})
        except:
            self._attributes.update({"Instructor":str("Unavailable")})
            _LOGGER.debug("Error Updating Peloton Attribute - Instructor")
        try:
            self._attributes.update({"Workout Image":str(workout_latest["ride"]["image_url"])})
        except:
            self._attributes.update({"Workout Image":str("Unavailable")})
            _LOGGER.debug("Error Updating Peloton Attribute - Workout Image")
        try:
            self._attributes.update({"Heart Rate Bpm":str(stats_latest["metrics"][4]["average_value"])})
        except:
            self._attributes.update({"Heart Rate Bpm":str("Unavailable")})
            _LOGGER.debug("Error Updating Peloton Attribute - Heart Rate Bpm")
        try:
            self._attributes.update({"Resistance %":str(stats_latest["metrics"][2]["average_value"])})
        except:
            self._attributes.update({"Resistance %":str("Unavailable")})
            _LOGGER.debug("Error Updating Peloton Attribute - Resistance Percentage")
