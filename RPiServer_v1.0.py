"""
======================================
*** Smart AC System Server Program ***
======================================
This program:
    1. Logs the living room (Arduino) temperature over time
    2. Logs the study (Raspberry Pi) temperature over time
It does this by keeping track of time, and every minute, logging the study temperature from its own DHT11 sensor and asking the Arduino to provide its temperature - that is, publish an MQTT message asking for it and waiting to receive it back.
    3. Receives and processes occupancy change messages from the Arduino

Other things this server program does are:
    4. Be a translation layer between one or more clients (e.g. an MQTT app, or a CLI client) and the Arduino, to:
        a. Turn AC on
        b. Turn AC off
        c. Turn AC temp up
        d. Turn AC temp down
        e. Change AC mode
        f. Advise whether the Arduino is responding to messages
        g. Provide system status (room occupancy, AC power status, target temp, actual temp, etc.)
        h. Provide temperature in living room and study
It does this by receiving MQTT messages and then sending out other MQTT messages: to the Arduino in the case of a-e, and back to the client in the case of f-h.

Lastly, the server program has some 'smart' logic built into it:
    5. It keeps track of room occupancy
    6. When the user turns the AC on, if the room is unoccupied, it switches the AC to a loud 'super' mode to get the room to the target temperature more quickly
    7. When the room becomes occupied, it switches the AC to quiet mode
    8. If the AC is on and the room becomes unoccupied, a timer is started; if this timer expires before the room is reoccupied, the AC is automatically switched off.
    9. If the room is reoccupied during the timer period, the timer is cancelled.
"""

import paho.mqtt.client as mqtt
import datetime
import time
import board
import adafruit_dht
import warnings
# This is just to suppress a warning about a deprecated MQTT callback; nothing more sinister.
warnings.filterwarnings('ignore')

# Our log file, to which our global log - also an MQTT channel - is written.
logFile = "logFile.txt"

# Global variables that are written to in functions and read elsewhere.
arduinoAvailable = "N/A"
arduinoTemp = None
rpiTemp = None
roomOccupancy = "N/A"
priorRoomOccupancy = None
systemMode = "N/A"
systemTargetTemp = 16

# Variables containing the bounds/parameters of our particular system
systemPowerState = "off"
validPowerStates = ["on", "off"]
validModes = ["quiet", "super", "cooling"]
validTemps = [16, 17, 18, 19, 20, 21, 22, 23, 24, 25]
timeoutState = False
timeoutMinutes = 5

# Device locations
arduinoLocation = "upstairs living room"
rpiLocation = "downstairs study"

# MQTT channels
# Logs
globalLog = "SmartACSystem/global/log"
serverLogNotice = "RPiServer/notice/log"
# Channels on which the server sends commands and requests to the Arduino
serverTempCommand = "RPiServer/command/temp"
serverModeCommand = "RPiServer/command/mode"
serverPowerCommand = "RPiServer/command/power"
serverTempRequest = "RPiServer/request/temp"
# Channels on which the server receives information from the Arduino
arduinoLogNotice = "arduino/notice/log"
arduinoTempNotice = "arduino/notice/temp"
arduinoOccChangeNotice = "arduino/notice/occ_change"
# Channels on which the server sends notices to user cliends
serverArduinoUpNotice = "RPiServer/notice/arduino_up"
serverTempNotice_arduino = "RPiServer/notice/temp_arduino"
serverTempNotice_rpi = "RPiServer/notice/temp_rpi"
serverTargetTempNotice = "RPiServer/notice/temp_target"
serverModeNotice = "RPiServer/notice/mode"
serverPowerStateNotice = "RPiServer/notice/power"
serverOccupancyNotice = "RPiServer/notice/occupancy"
serverTimeoutNotice = "RPiServer/notice/timeout"
# Channels on which the server receives commands and requests from the user
userRefreshRequest = "user/request/all"
userTempCommand = "user/command/temp"
userModeCommand = "user/command/mode"
userPowerCommand = "user/command/power"
userUpdateOccCommand = "user/command/occ_change"

# Listify the subscription topics so we can iterate through them in our `on_connect` method
subscribeTopics = [arduinoLogNotice, arduinoTempNotice, arduinoOccChangeNotice,
                   userRefreshRequest, userTempCommand, userModeCommand, userPowerCommand,
                   serverLogNotice] # We also subscribe to our own server log so we can re-emit it to the global log.

# MQTT helper functions
def on_connect(client, userdata, flags, rc):
    print(f"Connected with result code {rc}")
    for topic in subscribeTopics:
        client.subscribe(topic)

def on_message(client, userdata, message):

    # Make sure our function is using global variables rather than making its own local variables
    global arduinoAvailable
    global arduinoTemp
    global roomOccupancy
    global priorRoomOccupancy
    global systemPowerState
    global systemMode
    global systemTargetTemp
    
    topic = message.topic
    payload = message.payload.decode()

    # Temperature notification from Arduino
    if topic == arduinoTempNotice:
        # Set flag to show Arduino is still responding to messages
        arduinoAvailable = True
        try:
            arduinoTemp = float(payload)
            client.publish(serverLogNotice, f"Temperature of {arduinoTemp} received from {arduinoLocation} Arduino and processed", 0)
        except ValueError:
            client.publish(serverLogNotice, f"Invalid payload of {payload} received for {arduinoLocation} Arduino temperature.")
        

    # Occupancy change notification from Arduino 
    if topic == arduinoOccChangeNotice:
        # We don't care about room occupancy if the system is off
        if systemPowerState == "off":
            return
        try:
            occChange = int(payload)
            priorRoomOccupancy = roomOccupancy
            roomOccupancy += occChange
            if roomOccupancy < 0:
                roomOccupancy = 0
            client.publish(serverLogNotice, f"Occupancy change registered; updated from {priorRoomOccupancy} to {roomOccupancy}")
        except ValueError:
            client.publish(serverLogNotice, f"Invalid payload of {payload} received for {arduinoLocation} Arduino occupancy change.")

    # User client data refresh
    if topic == userRefreshRequest:
        client.publish(serverTempNotice_arduino, arduinoTemp)
        client.publish(serverTempNotice_rpi, rpiTemp)
        client.publish(serverPowerStateNotice, systemPowerState)
        client.publish(serverModeNotice, systemMode)
        client.publish(serverTargetTempNotice, systemTargetTemp)
        client.publish(serverOccupancyNotice, roomOccupancy)
        client.publish(serverArduinoUpNotice, arduinoAvailable)
        if systemPowerState == "off" or timeoutState == False:
            timeoutString = "N/A"
        else:
            timeoutString = str(timeoutEndTime.strftime("%H:%M"))
        client.publish(serverTimeoutNotice, timeoutString)
        client.publish(serverLogNotice, f"Refresh request from user client; sent all parameters.")
    
    # Commands from user
    # Power on and off
    if topic == userPowerCommand:
        if payload in validPowerStates:
            client.publish(serverPowerCommand, payload)
            client.publish(serverLogNotice, f"Received power command '{payload}' from user client; forwarded to Arduino.")
            # If the system has just been turned on, set it to super mode and the target temperature automatically
            if systemPowerState == "off" and payload == "on":
                # Wait a little bit between IR commands
                time.sleep(0.5)
                client.publish(serverModeCommand, "super")
                time.sleep(0.5)
                client.publish(serverTempCommand, systemTargetTemp)
                # Update room occupancy to zero if it was set to the system off status of "N/A"
                if not(is_number(roomOccupancy)):
                    roomOccupancy = 0
                systemMode = "super"
            # If system has been turned off, revert occupancy and mode to N/A
            if systemPowerState == "on" and payload == "off":
                roomOccupancy = "N/A"
                systemMode = "N/A"
            # Update system state
            systemPowerState = payload
        else:
            client.publish(serverLogNotice, f"Invalid payload of {payload} received from user client for {arduinoLocation} Arduino power command.")
        return
    # Change AC mode
    if topic == userModeCommand:
        if payload in validModes:
            client.publish(serverModeCommand, payload)
            client.publish(serverLogNotice, f"Received mode command '{payload}' from user client; forwarded to Arduino.")
            systemMode = payload
        else:
            client.publish(serverLogNotice, f"Invalid mode '{payload}' received from user client.")
    # Change AC temp
    if topic == userTempCommand:
        try:
            temp = int(payload)
            if temp in validTemps:
                client.publish(serverTempCommand, temp)
                client.publish(serverLogNotice, f"Received temp command '{temp}' from user client; forwarded to Arduino.")
                systemTargetTemp = temp
            else:
                client.publish(serverLogNotice, f"Received temperature {temp} from user client for {arduinoLocation} Arduino. Temp must be between {min(validTemps)} and {max(validTemps)} degrees.")
        except ValueError:
            client.publish(serverLogNotice, f"Invalid payload of {payload} received from user client for {arduinoLocation} Arduino target temperature command.")
    # Update occupancy
    if topic == userUpdateOccCommand:
        print("Update occupancy command received")
        try:
            newOccupancy = int(payload)
            if newOccupancy >= 0:
                priorRoomOccupancy = roomOccupancy
                roomOccupancy = newOccupancy
            else:
                client.publish(serverLogNotice, f"Invalid occupancy figure of {newOccupancy} provided by user client. Occupancy must be >= 0.")
        except ValueError:
            client.publish(serverLogNotice, f"Invalid payload of {payload} received from user client for room occupancy update.")
    
    
    # Write any logs to a logfile
    if "/notice/log" in topic:
        fstring = f"{datetime.datetime.now()}\t{topic}\t{payload}\n"
        with open("serverLog.txt", "a") as log:
           log.write(fstring)
        # And re-emit to a global log
        client.publish(globalLog, fstring)

# MQTT setup
mqttClient = mqtt.Client()
mqttClient.on_connect = on_connect
mqttClient.on_message = on_message
mqttClient.connect("localhost", 1883, 65535) # Connect to MQTT broker on Raspberry Pi; set timeout/keepalive to max.

# Start MQTT loop in the background
mqttClient.loop_start()

# RPi temperature sensor setup
rpiTempSensor = adafruit_dht.DHT11(board.D4)

# Helper function for checking room occupancy, as we set it to "N/A" when the system is off for pretty-printing purposes.
def is_number(var):
    return isinstance(var, (int, float))

# Header message for program, once connection established, before starting main loop
print("Smart AC system server now active. Press Ctrl-C to quit.")

# Main loop
try:
    while True:
        # Every minute, request the temperature from the Arduino
        if (int(datetime.datetime.now().timestamp()) % 60 == 0):
            # Check to see if the Arduino responded to the last temperature request; if not, note this to log and reset the Arduino temperature to None
            if arduinoAvailable == False:
                mqttClient.publish(serverLogNotice, f"Arduino did not respond to last temperature request.")
                arduinoTemp = None
            # Set Arduino availability flag to be false. This will be reset to true by the Arduino's response
            arduinoAvailable = False
            # Request the temperature
            mqttClient.publish(serverLogNotice, "Requesting temperature from Arduino.")
            mqttClient.publish(serverTempRequest, "0") # Payload is irrelevant for temp request, but can't be blank
            # Update the RPi temperature at the same time
            try:
                rpiTemp = rpiTempSensor.temperature
            except RuntimeError as error:
                print(error.args[0])
                continue
            mqttClient.publish(serverLogNotice, f"Temperatures recorded: {arduinoTemp} for {arduinoLocation} Arduino and {rpiTemp} for {rpiLocation} Raspberry Pi")
        
        # Once the room is occupied, turn the AC to quiet mode
        if is_number(roomOccupancy) and roomOccupancy > 0 and systemMode != "quiet":
            mqttClient.publish(serverModeCommand, "quiet")
            systemMode = "quiet"

        # If occupancy has changed to 0, start a timer to switch off the AC after a period of inoccupancy
        if systemPowerState == "on" and roomOccupancy == 0 and timeoutState == False:
            # Start a timer
            timeoutEndTimestamp = datetime.datetime.now().timestamp() + (timeoutMinutes * 60)
            timeoutEndTime = datetime.datetime.fromtimestamp(timeoutEndTimestamp)
            mqttClient.publish(serverLogNotice, f"Room unoccupied; timeout triggered: system will turn off at {timeoutEndTime} unless room is reoccupied.")
            timeoutState = True

        # If the inoccupancy timer is active and the room is reoccupied, cancel the timer
        if is_number(roomOccupancy) and roomOccupancy > 0 and timeoutState == True:
            timeoutState = False
            mqttClient.publish(serverLogNotice, f"Room reoccupied; timeout cancelled.")
            
        # If the timer has reached zero, turn the system off
        if timeoutState == True and datetime.datetime.now().timestamp() > timeoutEndTimestamp:
            mqttClient.publish(serverPowerCommand, "off")
            systemPowerState = "off"
            timeoutState = False
            roomOccupancy = "N/A"
            mqttClient.publish(serverLogNotice, f"Timeout expired; system turned off.")
            
        # If the system has been manually switch off, cancel the timer if there is one
        if systemPowerState == "off" and timeoutState == True:
            timeoutState = False
            mqttClient.publish(serverLogNotice, f"System turned off; timer cancelled.")

        time.sleep(1)

except KeyboardInterrupt:
    print("Exiting...")
finally:
    mqttClient.loop_stop()
    mqttClient.disconnect()
