# Smart AC Control System
## Introduction
Welcome! This repo contains an air conditioner control system I created for my SI210 final project, comprising:
1. A Raspberry Pi on which runs a server program written in Python;
2. An Arduino Nano 33 IoT on which runs a program that controls the AC in another room and monitors conditions in that room. 
3. An user-facing MQTT client that communicates with the Python server to control the AC, see system status, etc.

I recommend you view the source files for the Arduino program and the Raspberry Pi server program for more details as to their functionality.

## Usage
### Arduino
Configure your Arduino hardware setup per the `TODO filename` circuit diagram and upload the Arduino program to your board.

### Raspberry Pi server
The server program utilises a few libraries that are not available via `apt` on Raspberry Pi. Because RPi's Python install is externally managed, to utilise these libraries you will need to create a virtual environment (*venv*) in which your server runs. Below are instructions for creating this environment and installing the necessary packages.

I used the contraction "SMArt Living Room Air Conditioner ('SMALRAC')" for my system during development, so I used this naming convention for my venv:
```bash
python -m venv smalrac
smalrac/bin/pip install RPi.GPIO
smalrac/bin/pip install adafruit-circuitpython-dht
smalrac/bin/pip install paho-mqtt
```

For other devices (such are your Arduino and your MQTT User Client) to communicate with the server, you'll also need to make sure your **MQTT broker** is set up. I used Mosquitto, which can be installed with:
```bash
sudo apt-get install mosquitto mosquitto-clients
```

Because the whole system runs on your local network, with no Internet communication, devices to not log in. Therefore, you'll need to update your Mosquitto configuration file to allow anonymous devices to connect. To do this, update your `/etc/mosquitto/conf.d/mosquitto.conf` file to contain the following lines:
```
allow_anonymous true
listener 1883 0.0.0.0
```

Start your Mosquitto broker with:
```bash
sudo /etc/init.d/mosquitto start
```

Finally, with your Mosquitto broker running, run the server program in your venv:
```bash
smalrac/bin/python3 smalrac_server_v1.0.py
```

### MQTT User Client
I utilised a free MQTT app called **IoT MQTT Panel** available on both the [Apple App Store](https://apps.apple.com/pl/app/iot-mqtt-panel/id6466780124) and the [Google Play Store](https://play.google.com/store/apps/details?id=snr.lab.iotmqttpanel.prod&hl=en_AU&pli=1). The `IoTMQTTPanel_config.json` JSON configuration file in this repo can be used to quickly set up a user interface. All you need to do is update the `yourServeriPAddress`, `yourServerUserName` and `yourServerPassword` strings in this file with your Raspberry Pi's IP address, username and password, respectively.