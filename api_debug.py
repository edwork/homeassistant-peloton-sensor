#!/usr/bin/python3
"""This script will give you a giant dictionary that can be used."""

# pip3 install pylotoncycle
import pylotoncycle

# Fill this in!
username = 'username'
password = 'pa$$word'

# Logic
conn = pylotoncycle.PylotonCycle(username, password)
workouts = conn.GetRecentWorkouts(5)
workout = workouts[0]

# Output a giant dictionary
print(workout)
