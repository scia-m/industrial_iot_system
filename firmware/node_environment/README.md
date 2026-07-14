# Node Environment Firmware

This folder contains the firmware for the `node_environment` ESP32/ESP-IDF application.

## Overview

The `node_environment` node is part of the industrial IoT system and is responsible for collecting environmental sensor data and reporting it through the gateway. It is built using ESP-IDF v6 and includes the application code, managed components, and build configuration.

## Build Requirements

- ESP-IDF v6
- Python 3
- Required ESP-IDF tools installed and available in your shell environment

## Setup

Source the ESP-IDF environment for v6:

   ```bash
   . /path/to/esp-idf/export.sh
   ```


## Build

From the `firmware/node_environment` directory, run:

```bash
idf.py build
```

## Flash

To flash the built firmware to the device, run:

```bash
idf.py flash
```

## Notes

- The `sdkconfig` file in this directory contains build configuration options for this node.
- If required, adjust the partition table or other settings before building.
- Use `idf.py menuconfig` to customize build settings.
