#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from gateway.mqtt.__main__ import main as mqtt_main


def load_config(path: str | None = None) -> dict:
    config_path = Path(path or os.getenv("MQTT_SERVICE_CONFIG", str(ROOT / "services" / "mqtt_config.json")))
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def run() -> None:
    config = load_config()
    os.environ.setdefault("MQTT_BROKER", config.get("broker", "localhost"))
    os.environ.setdefault("MQTT_PORT", str(config.get("port", 1883)))
    os.environ.setdefault("MQTT_CLIENT_ID", config.get("client_id", "gateway-mqtt-service"))
    os.environ.setdefault("MQTT_USERNAME", config.get("username", ""))
    os.environ.setdefault("MQTT_PASSWORD", config.get("password", ""))
    os.environ.setdefault("MQTT_KEEPALIVE", str(config.get("keepalive", 60)))
    os.environ.setdefault("MQTT_TOPICS", " ".join(config.get("topics", ["factory/+/telemetry", "factory/+/heartbeat", "factory/+/status"])))
    os.environ.setdefault("GATEWAY_DB_PATH", str(ROOT / "gateway.db"))
    mqtt_main()


if __name__ == "__main__":
    run()
