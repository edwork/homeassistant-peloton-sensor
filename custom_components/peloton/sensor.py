"""A platform which allows you to get current and past ride data from Peloton."""

from datetime import timedelta
import logging

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
    def device_state_attributes(self):
        """Return device specific state attributes."""
        return self._attributes

    def update(self):
        """Fetch new state data for the sensor."""

        conn = pylotoncycle.PylotonCycle(self.user, self.password)
        workouts = conn.GetRecentWorkouts(1)
        workout = workouts[0]

        if (workout["status"]== 'COMPLETE'):
            self._state = 'Complete'
        elif (workout["status"]== 'IN_PROGRESS'):
            self._state = 'Active'
        else:
            self._state = workout["UNKNOWN"]

        # Attempting to handle errors in case the API changes
        try:
            self._attributes.update({"Workout Type":str(workout["fitness_discipline"])})
            self._attributes.update({"Ride Title":str(workout["ride"]["title"])})
            self._attributes.update({"Description":str(workout["ride"]["description"])})
            self._attributes.update({"Duration Min":str((workout["ride"]["duration"])//60)})
            self._attributes.update({"Leaderboard Rank":str(workout["leaderboard_rank"])})
            self._attributes.update({"Output Kj":str((workout["total_work"]//1000)+(workout["total_work"]%1000>0))})
            self._attributes.update({"Distance Mi":str(workout["overall_summary"]["distance"])})
            self._attributes.update({"Calories KCal":str(int(workout["overall_summary"]["calories"]))})
            self._attributes.update({"Heart Rate Bpm":str(workout["overall_summary"]["heart_rate"])})
            self._attributes.update({"Heart Rate Average Bpm":str(workout["overall_summary"]["avg_heart_rate"])})
            self._attributes.update({"Heart Rate Max Bpm":str(workout["overall_summary"]["max_heart_rate"])})
            self._attributes.update({"Resistance %":str(workout["overall_summary"]["resistance"])})
            self._attributes.update({"Resistance Average %":str(workout["overall_summary"]["avg_resistance"])})
            self._attributes.update({"Resistance Max %":str(workout["overall_summary"]["max_resistance"])})
            self._attributes.update({"Speed Mph":str(workout["overall_summary"]["speed"])})
            self._attributes.update({"Speed Average Mph":str(workout["overall_summary"]["avg_speed"])})
            self._attributes.update({"Speed Max Mph":str(workout["overall_summary"]["max_speed"])})
            self._attributes.update({"Speed Kph":str(round(((workout["overall_summary"]["speed"])*1.60934),2))})
            self._attributes.update({"Speed Average Kph":str(round(((workout["overall_summary"]["avg_speed"])*1.60934),2))})
            self._attributes.update({"Speed Max Kph":str(round(((workout["overall_summary"]["max_speed"])*1.60934),2))})
            self._attributes.update({"Cadence Rpm":str(workout["overall_summary"]["cadence"])})
            self._attributes.update({"Cadence Average Rpm":str(workout["overall_summary"]["avg_cadence"])})
            self._attributes.update({"Cadence Max Rpm":str(workout["overall_summary"]["max_cadence"])})
            self._attributes.update({"Power W":str(workout["overall_summary"]["power"])})
            self._attributes.update({"Power Average W":str(workout["overall_summary"]["avg_power"])})
            self._attributes.update({"Power Max W":str(workout["overall_summary"]["max_power"])})
            self._attributes.update({"Instructor":str(workout["instructor_name"])})
        except:
            print("Error - Check to make sure the API hasn't changed")
