/*
=======================================
*** Smart AC System Arduino Program ***
=======================================
This program runs on an Arduino Nano 33 IoT, and is designed to be integrated into a wider system containing a server program, running on a Raspberry Pi, and one or more user client programs to control the system in a friendly manner.alignas

This program:
  1. Responds to temperature requests from the RPi server by sending back the temperature recorded on its sensor
  2. Receives commands from the server and sends these out as IR blasts to the AC system
  3. Uses two HC-SR04 sensors, spaced about 30cm apart at the entrance to the room in which the Arduino is located, to detect people entering or leaving said room. When it detects an occupancy change, it sends this to the Arduino server to keep track of and act on accordingly.
*/

#include <WiFiNINA.h>
#include <ArduinoMqttClient.h>
#include <IRremote.hpp>
#include "DHT.h"
#include "secrets.h"     // WiFi details
#include "ir_commands.h" // Commands - in the form of microsecond pulse timings - for my Hisense aircon

// debug mode prints to serial
const bool debug = false;

// Temperature sensor details
#define IR_SEND_PIN 5
#define DHTPIN 7
#define DHTTYPE DHT11
DHT dht(DHTPIN, DHTTYPE);

// WiFi details
char ssid[] = SECRET_SSID;
char pass[] = SECRET_PASS;
WiFiClient wifiClient;

// MQTT broker details
const char broker[] = "192.168.0.242";
int brokerPort = 1883;
MqttClient mqttClient(wifiClient);
String payload;
String topic;
String notice; // Used to store text before printing to both Serial and MQTT

// MQTT channels
String serverTempRequest = "RPiServer/request/temp";
String serverTempCommand = "RPiServer/command/temp";
String serverModeCommand = "RPiServer/command/mode";
String serverPowerCommand = "RPiServer/command/power";
String arduinoOccChangeNotice = "arduino/notice/occ_change";
String arduinoTempNotice = "arduino/notice/temp";
String arduinoLogNotice = "arduino/notice/log";
String debugStream = "arduino/debug";

// Ultrasonic sensor details
const int innerSensorTriggerPin = 9;
const int innerSensorEchoPin = 10;
const int outerSensorTriggerPin = 11;
const int outerSensorEchoPin = 12;
const int untriggeredDistance = 310;      // The untriggered distance. My sensor is about 3.1m from the wall.
const int triggerThresholdDistance = 220; // The delta threshold for considering a trigger. My door is about 90cm wide.
String stateSequence = "N";               // Keep track of sequence of states to determine if a sequence corresponds to a person entering or exiting the room. "N" means neither are triggered.

// Occupancy details
int occupants, priorOccupants = 0;

void sendMqttMessage(String topic, String message)
{
    mqttClient.beginMessage(topic);
    mqttClient.print(message);
    mqttClient.endMessage();
}

void setup()
{
    // Initialise serial port
    if (debug)
    {
        Serial.begin(9600);
        while (!Serial)
            ;
    }

    // Connect to Wi-Fi
    if (debug)
    {
        Serial.print("Attempting to connect to SSID: ");
        Serial.println(SECRET_SSID);
    }
    while (WiFi.status() != WL_CONNECTED)
    {
        WiFi.begin(ssid, pass);
        if (debug)
        {
            Serial.print(".");
        }
        delay(1000);
    }
    if (debug)
    {
        Serial.println("\nConnected to WiFi.");
    }

    // Connect to MQTT broker
    if (debug)
    {
        Serial.print("Attempting to connect to MQTT broker ");
        Serial.println(broker);
    }
    // Wait for MQTT
    while (!mqttClient.connect(broker, brokerPort))
    {
        if (debug)
        {
            Serial.print("MQTT connection failure. Error code ");
            Serial.println(mqttClient.connectError());
        }
    }
    if (debug)
    {
        Serial.println("Now connected to broker.");
    }
    sendMqttMessage(arduinoLogNotice, "Arduino online and connected to MQTT broker.");

    // Subscribe to relevant topics
    mqttClient.subscribe(serverTempRequest);
    sendMqttMessage(arduinoLogNotice, "Subscribed to topic " + serverTempRequest);
    mqttClient.subscribe(serverTempCommand);
    sendMqttMessage(arduinoLogNotice, "Subscribed to topic " + serverTempCommand);
    mqttClient.subscribe(serverPowerCommand);
    sendMqttMessage(arduinoLogNotice, "Subscribed to topic " + serverPowerCommand);
    mqttClient.subscribe(serverModeCommand);
    sendMqttMessage(arduinoLogNotice, "Subscribed to topic " + serverModeCommand);

    // Initialise the IR LED
    IrSender.begin(IR_SEND_PIN, ENABLE_LED_FEEDBACK, LED_BUILTIN);

    // Initialise temperature sensor
    dht.begin();
}

void loop()
{
    // Keep MQTT connection alive
    // mqttClient.poll();

    // How long does all the MQTT message processing take?
    unsigned long start = millis();

    // Check for messages
    int msgReceived = mqttClient.parseMessage();
    if (msgReceived)
    {
        // Receive the message
        topic = String(mqttClient.messageTopic());
        payload = "";
        while (mqttClient.available())
        {
            payload += (char)mqttClient.read();
        }

        // Log receipt of message
        notice = "Message received for topic '" + topic + "': " + payload;
        sendMqttMessage(arduinoLogNotice, notice);
        if (debug)
        {
            Serial.println(notice);
        }

        // Parse the message to determine its type
        int subTopicSplit = topic.indexOf('/');
        int actionSplit = topic.lastIndexOf('/');
        String subTopic = topic.substring(subTopicSplit + 1, actionSplit);
        String action = topic.substring(actionSplit + 1);

        // Track status of message action
        int messageProcessingStatus;

        // Process AC commands
        if (subTopic == "command")
        {
            messageProcessingStatus = sendIrCommand(action, payload);
            if (messageProcessingStatus == 0)
            {
                notice = "Sent IR blast for " + action + " " + payload + ".";
                sendMqttMessage(arduinoLogNotice, notice);
                if (debug)
                {
                    Serial.println(notice);
                }
            }

            unsigned long end = millis();
            unsigned long duration = end - start;
            if (debug)
            {
                Serial.print("Milliseconds taken to process MQTT message and send IR command: ");
                Serial.println(duration);
            }
        }

        // Process temperature request
        if (subTopic == "request")
        {
            messageProcessingStatus = processRequest(action, payload);
            if (messageProcessingStatus == 0)
            {
                notice = "Successfully actioned request for " + action + ".";
                sendMqttMessage(arduinoLogNotice, notice);
                if (debug)
                {
                    Serial.println(notice);
                }
            }
        }

        if (messageProcessingStatus != 0)
        {
            notice = "Invalid action '" + action + "', or invalid payload '" + payload + "' for action '" + action + "'.";
            sendMqttMessage(arduinoLogNotice, notice);
            if (debug)
            {
                Serial.println(notice);
            }
        }
    }

    // Check for room occupancy change
    int occupancyChange = detectOccupancyChange();
    if (occupancyChange != 0)
    {
        // Send via MQTT
        sendMqttMessage(arduinoOccChangeNotice, String(occupancyChange));
        // Add to log
        notice = "Sent message on topic " + arduinoOccChangeNotice + " of occupancy change of " + occupancyChange + ".";
        sendMqttMessage(arduinoLogNotice, notice);
        if (debug)
        {
            Serial.println(notice);
        }
    }
}

// Process MQTT messages that are requests
int processRequest(String request, String argument)
{
    if (request == "temp")
    {
        float t = dht.readTemperature();
        sendMqttMessage(arduinoTempNotice, String(t));
    }
    return 0;
}

// Process MQTT messages that are commands
int sendIrCommand(String command, String argument)
{
    // Power commands
    if (command == "power")
    {
        if (argument == "on")
        {
            IrSender.sendRaw(turnOn, bufferLength, 38);
        }
        else if (argument == "off")
        {
            IrSender.sendRaw(turnOff, bufferLength, 38);
        }
        else
        {
            return -1; // Error
        }
        return 0; // Success
    }

    // Mode commands
    if (command == "mode")
    {
        if (argument == "cooling")
        {
            IrSender.sendRaw(modeCooling, bufferLength, 38);
        }
        else if (argument == "super")
        {
            IrSender.sendRaw(modeSuper, bufferLength, 38);
        }
        else if (argument == "quiet")
        {
            IrSender.sendRaw(modeQuiet, bufferLength, 38);
        }
        else
        {
            return -1; // Error
        }
        return 0; // Success
    }

    // Temp commands
    if (command == "temp")
    {
        char temp = argument.charAt(1);

        // TODO
        switch (temp)
        {
        case '6':
            IrSender.sendRaw(temp16, bufferLength, 38);
            break;
        case '7':
            IrSender.sendRaw(temp17, bufferLength, 38);
            break;
        case '8':
            IrSender.sendRaw(temp18, bufferLength, 38);
            break;
        case '9':
            IrSender.sendRaw(temp19, bufferLength, 38);
            break;
        case '0':
            IrSender.sendRaw(temp20, bufferLength, 38);
            break;
        case '1':
            IrSender.sendRaw(temp21, bufferLength, 38);
            break;
        case '2':
            IrSender.sendRaw(temp22, bufferLength, 38);
            break;
        case '3':
            IrSender.sendRaw(temp23, bufferLength, 38);
            break;
        case '4':
            IrSender.sendRaw(temp24, bufferLength, 38);
            break;
        case '5':
            IrSender.sendRaw(temp25, bufferLength, 38);
            break;
        default:
            return -1; // Error
        }
        return 0; // Success
    }

    // Not a valid command if we got here
    return -1;
}

// Measure distance with HC-SR04 sensor
int measureDistance(int trigPin, int echoPin)
{
    // Send a pulse
    pinMode(trigPin, OUTPUT);
    digitalWrite(trigPin, LOW);
    delayMicroseconds(2);
    digitalWrite(trigPin, HIGH);
    delayMicroseconds(10);
    digitalWrite(trigPin, LOW);

    // Receive the echo
    pinMode(echoPin, INPUT);
    double duration = pulseIn(echoPin, HIGH, 100000);

    // Calculate and return the distance. Sound travels 0.0343 cm per microsecond. Echo delay is round-trip distance, so we divide by 2 for object distance.
    return (duration * 0.0343) / 2;
}

int detectOccupancyChange()
{
    // Read distances
    int innerSensorDistance = measureDistance(innerSensorTriggerPin, innerSensorEchoPin);
    int outerSensorDistance = measureDistance(outerSensorTriggerPin, outerSensorEchoPin);

    // Determine state
    char state;
    if (innerSensorDistance < untriggeredDistance - triggerThresholdDistance && outerSensorDistance < untriggeredDistance - triggerThresholdDistance)
    {
        state = 'B'; // Both sensors
    }
    else if (innerSensorDistance < untriggeredDistance - triggerThresholdDistance)
    {
        state = 'I'; // Inner sensor
    }
    else if (outerSensorDistance < untriggeredDistance - triggerThresholdDistance)
    {
        state = 'O'; // Outer sensor
    }
    else
    {
        state = 'N'; // Neither sensor
    }

    // If the sensor is untriggered and we're at the beginning of a state sequence, don't bother appending to the state sequence
    if (state == 'N' && stateSequence.length() == 1)
    {
        return 0;
    }

    // Otherwise, append to the state sequence
    stateSequence += state;

    // If we've completed a state sequence, i.e. completed a sequence of sensor trigger states, we now need to check if the sequence corresponds with someone moving in or out of the room.
    if (stateSequence.charAt(stateSequence.length() - 1) == 'N' && stateSequence.length() > 1)
    {
        // Print the completed state sequence for debugging purposes
        if (debug)
        {
            Serial.print("State sequence: ");
            Serial.println(stateSequence);
        }

        priorOccupants = occupants;

        // I've found that the when travelling out of the room, the sensor goes N to oscillating between O and BO (OBOBOBOBO), to oscillating between B and I (BIBIBIBIBI) and then back to N.
        // This means that, for outward travel, the first instance of O should be earlier in the string than the first instance of I (e.g. "NOBOBOBOBOBIBIBIBIBIBIN").
        // It will be the opposite for inward travel.
        int firstI = stateSequence.indexOf('I');
        int firstO = stateSequence.indexOf('O');
        int lastI = stateSequence.lastIndexOf('I');
        int lastO = stateSequence.lastIndexOf('O');
        // State sequences that don't have both the inner and outer sensors being triggered don't correspond to occupancy change, so don't process these sequences
        if (firstI == -1 || firstO == -1)
        {
            // Reset the state sequence
            stateSequence = "N";
            // And then don't do anything else.
            return 0;
        }
        else
        {
            // If our state sequence contains both an I and an O, update the occupancy based on the logic above.
            if (firstI < firstO)
            {
                // Reset the state sequence
                stateSequence = "N";
                return 1;
            }
            if (firstO < firstI)
            {
                // Reset the state sequence
                stateSequence = "N";
                return -1;
            }
        }
    }

    // If we haven't completed a state sequence, occupancy hasn't changed: return 0.
    return 0;
}