"""Peloton integration constants."""

from datetime import timedelta

DOMAIN = "peloton"
INTEGRATION_NAME = "Peloton"

# How often the coordinator polls Peloton.
SCAN_INTERVAL = timedelta(seconds=10)
# How often the profile (/api/me) and settings are refreshed between workouts.
PROFILE_REFRESH_INTERVAL = timedelta(hours=1)
# Samples per performance graph request; the last sample is always included.
PERFORMANCE_GRAPH_EVERY_N = 50
