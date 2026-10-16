"""Peloton integration constants."""

from datetime import timedelta

DOMAIN = "peloton"
INTEGRATION_NAME = "Peloton"

# Options (seconds, seconds, minutes) and their defaults and limits.
CONF_IDLE_INTERVAL = "idle_interval"
CONF_ACTIVE_INTERVAL = "active_interval"
CONF_MAX_WORKOUT_MINUTES = "max_workout_minutes"
DEFAULT_IDLE_INTERVAL = 15
DEFAULT_ACTIVE_INTERVAL = 10
DEFAULT_MAX_WORKOUT_MINUTES = 240
IDLE_INTERVAL_RANGE = (10, 60)
ACTIVE_INTERVAL_RANGE = (5, 60)
MAX_WORKOUT_MINUTES_RANGE = (30, 600)

# A workout still marked in progress this long after its class should have
# ended is treated as abandoned.
WORKOUT_GRACE = timedelta(minutes=15)
# How often the profile (/api/me) and settings are refreshed between workouts.
PROFILE_REFRESH_INTERVAL = timedelta(hours=1)
# Samples per performance graph request; the last sample is always included.
PERFORMANCE_GRAPH_EVERY_N = 50
# Failed polls in a row before entities become unavailable.
TOLERATED_FAILED_POLLS = 3
# Rate limits: a poll is never retried later than this (seconds), and without
# a usable Retry-After the wait starts here and doubles per failed poll.
MAX_RETRY_AFTER = 3600
RATE_LIMIT_BACKOFF = 60
RATE_LIMIT_MAX_BACKOFF = 900
