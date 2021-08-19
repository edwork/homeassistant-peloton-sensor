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
        workouts = conn.GetRecentWorkouts(2)
        workout_1 = workouts[0]
        w_id_1 = workout_1["id"]
        stats_1 = conn.GetWorkoutMetricsById(w_id_1)

        if (workout_1["status"]== 'COMPLETE'):
            self._state = 'Complete'
        elif (workout_1["status"]== 'IN_PROGRESS'):
            self._state = 'Active'
        else:
            self._state = workout["UNKNOWN"]

        # Attempting to handle errors in case the API changes
        try:
            self._attributes.update({"Workout Type":str(workout_1["fitness_discipline"])})
            self._attributes.update({"Ride Title":str(workout_1["ride"]["title"])})
            self._attributes.update({"Description":str(workout_1["ride"]["description"])})
            self._attributes.update({"Start Time":str(workout_1["start_time"])})
            self._attributes.update({"End Time":str(workout_1["end_time"])})
            self._attributes.update({"Duration Min":str((workout_1["ride"]["duration"])//60)})
            self._attributes.update({"Leaderboard Rank":str(workout_1["leaderboard_rank"])})
            self._attributes.update({"Leaderboard Users":str(workout_1["total_leaderboard_users"])})
            self._attributes.update({"Output Kj":str((workout_1["total_work"]//1000)+(workout_1["total_work"]%1000>0))})
            self._attributes.update({"Distance Mi":str(stats_1["summaries"][1]["value"])})
            self._attributes.update({"Calories KCal":str(int(stats_1["summaries"][2]["value"]))})
            self._attributes.update({"Heart Rate Average Bpm":str(stats_1["metrics"][4]["average_value"])})
            self._attributes.update({"Heart Rate Max Bpm":str(stats_1["metrics"][4]["max_value"])})
            self._attributes.update({"Resistance Average %":str(stats_1["metrics"][2]["average_value"])})
            self._attributes.update({"Resistance Max %":str(stats_1["metrics"][2]["max_value"])})
            self._attributes.update({"Speed Average Mph":str(stats_1["metrics"][3]["average_value"])})
            self._attributes.update({"Speed Max Mph":str(stats_1["metrics"][3]["max_value"])})
            self._attributes.update({"Speed Average Kph":str(round(((stats_1["metrics"][3]["average_value"])*1.60934),2))})
            self._attributes.update({"Speed Max Kph":str(round(((stats_1["metrics"][3]["max_value"])*1.60934),2))})
            self._attributes.update({"Cadence Average Rpm":str(stats_1["metrics"][1]["average_value"])})
            self._attributes.update({"Cadence Max Rpm":str(stats_1["metrics"][1]["max_value"])})
            self._attributes.update({"Power Average W":str(stats_1["metrics"][0]["average_value"])})
            self._attributes.update({"Power Max W":str(stats_1["metrics"][0]["max_value"])})
            self._attributes.update({"Total Work":str(workout_1["overall_summary"]["total_work"])})
            self._attributes.update({"Instructor":str(workout_1["instructor_name"])})
            self._attributes.update({"Workout Image":str(workout_1["ride"]["image_url"])})
            
            # Heart Rate Zones
            self._attributes.update({"HR Zone 1 Time":str(stats_1['effort_zones']['heart_rate_zone_durations']['heart_rate_z1_duration']//60) + ":" + str(stats_1['effort_zones']['heart_rate_zone_durations']['heart_rate_z1_duration'] % 60)})
            self._attributes.update({"HR Zone 2 Time":str(stats_1['effort_zones']['heart_rate_zone_durations']['heart_rate_z2_duration']//60) + ":" + str(stats_1['effort_zones']['heart_rate_zone_durations']['heart_rate_z2_duration'] % 60)})
            self._attributes.update({"HR Zone 3 Time":str(stats_1['effort_zones']['heart_rate_zone_durations']['heart_rate_z3_duration']//60) + ":" + str(stats_1['effort_zones']['heart_rate_zone_durations']['heart_rate_z3_duration'] % 60)})
            self._attributes.update({"HR Zone 4 Time":str(stats_1['effort_zones']['heart_rate_zone_durations']['heart_rate_z4_duration']//60) + ":" + str(stats_1['effort_zones']['heart_rate_zone_durations']['heart_rate_z4_duration'] % 60)})
            self._attributes.update({"HR Zone 5 Time":str(stats_1['effort_zones']['heart_rate_zone_durations']['heart_rate_z5_duration']//60) + ":" + str(stats_1['effort_zones']['heart_rate_zone_durations']['heart_rate_z5_duration'] % 60)})

            # #Current metrics
            self._attributes.update({"Heart Rate Bpm":str(stats_1["metrics"][4]["values"][-1])})
            self._attributes.update({"Resistance %":str(stats_1['metrics'][2]['values'][-1])})
            self._attributes.update({"Speed Mph":str(stats_1['metrics'][3]['values'][-1])})
            self._attributes.update({"Speed Kph":str(round(((stats_1['metrics'][3]['values'][-1])*1.60934),2))})
            self._attributes.update({"Cadence Rpm":str(stats_1['metrics'][1]['values'][-1])})
            self._attributes.update({"Power W":str(stats_1['metrics'][0]['values'][-1])})

        except:
            print("Error - Check to make sure the API hasn't changed")

 
