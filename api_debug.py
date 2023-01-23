"""This script will give you a giant dictionary that can be used."""
#!/usr/bin/python3

import getopt
import json
import sys
from typing import Any

import pylotoncycle


def main(argv: Any) -> None:
    """Output raw data from Peloton API to console."""
    username = ""
    password = ""
    try:
        opts, _ = getopt.getopt(argv, "hu:p:", ["user=", "pass="])
    except getopt.GetoptError:
        print("api_debug.py -u <user> -p <pass>")
        sys.exit(2)
    for opt, arg in opts:
        if opt == "-h":
            print("api_debug.py -u <user> -p <pass>")
            sys.exit()
        elif opt in ("-u", "--user"):
            username = arg
        elif opt in ("-p", "--pass"):
            password = arg
    try:
        conn = pylotoncycle.PylotonCycle(username, password)
    except pylotoncycle.pylotoncycle.PelotonLoginException:
        print("Login or Password incorrect")
    else:
        workouts = conn.GetRecentWorkouts(5)
        latest_workout = workouts[0]
        user_profile = conn.GetMe()
        latest_workout_metrics = conn.GetWorkoutMetricsById(workouts[0]["id"])

        print("\n==================[ USER PROFILE ]==================[\n")

        print(json.dumps(user_profile))

        print("\n==================[ LATEST WORKOUT OVERVIEW ]==================[\n")

        print(json.dumps(latest_workout))

        print("\n==================[ LATEST WORKOUT METRICS ]==================[\n")

        print(json.dumps(latest_workout_metrics))


if __name__ == "__main__":
    main(sys.argv[1:])
