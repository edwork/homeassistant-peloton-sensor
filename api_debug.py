#!/usr/bin/python3
"""This script will give you a giant dictionary that can be used."""
# pip3 install pylotoncycle
import pylotoncycle, sys, getopt
def main(argv):
    username = ''
    password = ''
    try:
        opts, args = getopt.getopt(argv,"hu:p:",["user=","pass="])
    except getopt.GetoptError:
        print ('api_debug.py -u <user> -p <pass>')
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-h':
            print ('api_debug.py -u <user> -p <pass>')
            sys.exit()
        elif opt in ("-u", "--user"):
            username = arg
        elif opt in ("-p", "--pass"):
            password = arg
    try:
        conn = pylotoncycle.PylotonCycle(username, password)
    except pylotoncycle.pylotoncycle.PelotonLoginException:
        print("Login or Password incorrect")
    except Exception as e:
        print("an error has occurred:" + str(e))
    else:
        workouts = conn.GetRecentWorkouts(5)
        workout = workouts[0]
        # Output a giant dictionary
        print(workout)
if __name__ == "__main__":
    main(sys.argv[1:])