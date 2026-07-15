# Gateway database module

This module provides a small SQLite-backed database layer for the gateway.

## What it stores
- Devices: node identity, availability, firmware, signal strength
- Measurements: flexible per-device measurements with type/value/unit/metadata
- Heartbeats: uptime and health information from MQTT heartbeats
- Events: gateway-generated event history
- Commands: history of outgoing MQTT commands
- FirmwareVersions: firmware history per device

## Usage
```python
from gateway.database import GatewayDatabase


db = GatewayDatabase("gateway/gateway.db")
db.initialize()

db.register_device(node_id="node_environment", firmware="1.0.0", status="ok", rssi=-58)
db.record_heartbeat(node_id="node_environment", uptime=1234, free_heap=182344, wifi_rssi=-58, firmware="1.0.0", status="ok")
db.record_measurement(node_id="node_environment", measurement_type="temperature", value=21.7, unit="C")
```
