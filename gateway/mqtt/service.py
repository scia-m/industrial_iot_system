import json
import logging
from typing import Any, Dict, Optional

from gateway.database import GatewayDatabase


class MQTTGatewayService:
    """Process incoming MQTT messages and persist them through the gateway database."""

    def __init__(self, db: Optional[GatewayDatabase] = None, logger: Optional[logging.Logger] = None):
        self.db = db or GatewayDatabase()
        self.logger = logger or logging.getLogger("gateway.mqtt")
        self.db.initialize()

    def handle_message(self, topic: str, payload: str) -> None:
        try:
            message = json.loads(payload)
        except json.JSONDecodeError as exc:
            self.logger.error("Invalid JSON payload: %s", exc)
            self.db.record_event(node_id=None, event_type="invalid_message", message=f"Invalid JSON payload: {exc}")
            return

        if not isinstance(message, dict):
            self.db.record_event(node_id=None, event_type="invalid_message", message="Payload must be a JSON object")
            return

        if topic.endswith("status"):
            self._handle_status(message, topic)
            return

        if topic.endswith("heartbeat"):
            self._handle_heartbeat(message)
            return

        if topic.endswith("telemetry"):
            self._handle_telemetry(message)
            return

        self.db.record_event(node_id=message.get("node_id"), event_type="unsupported_topic", message=f"Unsupported topic: {topic}")

    def _handle_telemetry(self, message: Dict[str, Any]) -> None:
        if not self._validate_telemetry_message(message):
            self.db.record_event(node_id=message.get("node_id"), event_type="invalid_telemetry", message="Telemetry schema validation failed")
            return

        node_id = str(message["node_id"])
        payload = message.get("payload", {})
        if not isinstance(payload, dict):
            self.db.record_event(node_id=node_id, event_type="invalid_telemetry", message="Telemetry payload must be an object")
            return

        self.db.record_event(node_id=node_id, event_type="telemetry_received", message="Telemetry received")
        self.db.register_device(node_id=node_id, status="online")

        for metric_name, metric_value in payload.items():
            if isinstance(metric_value, (int, float)):
                self.db.record_measurement(node_id=node_id, measurement_type=str(metric_name), value=float(metric_value))

    def _handle_status(self, message: Dict[str, Any], topic: str) -> None:
        node_id = self._extract_node_id(topic)
        status_value = message.get("status")
        if not isinstance(status_value, str) or not status_value.strip():
            self.db.record_event(node_id=node_id, event_type="invalid_status", message="Status message missing valid status")
            return

        self.db.register_device(node_id=node_id, status=status_value)
        self.db.record_event(node_id=node_id, event_type="status_received", message=f"Status updated to {status_value}")

    def _handle_heartbeat(self, message: Dict[str, Any]) -> None:
        if not self._validate_heartbeat_message(message):
            self.db.record_event(node_id=message.get("node_id"), event_type="invalid_heartbeat", message="Heartbeat validation failed")
            return

        node_id = str(message["node_id"])
        self.db.record_event(node_id=node_id, event_type="heartbeat_received", message="Heartbeat received")
        self.db.record_heartbeat(
            node_id=node_id,
            uptime=int(message["uptime"]),
            free_heap=message.get("free_heap"),
            wifi_rssi=message.get("wifi_rssi"),
            firmware=message.get("firmware"),
        )

    def _validate_telemetry_message(self, message: Dict[str, Any]) -> bool:
        required_fields = ["schema", "node_id", "type", "timestamp", "payload"]
        if not all(field in message for field in required_fields):
            return False
        if message.get("type") != "telemetry":
            return False
        if not isinstance(message.get("payload"), dict):
            return False
        if not isinstance(message.get("node_id"), str) or not message["node_id"].strip():
            return False
        if not isinstance(message.get("schema"), str):
            return False
        if not isinstance(message.get("timestamp"), (int, float)):
            return False
        return True

    def _validate_heartbeat_message(self, message: Dict[str, Any]) -> bool:
        required_fields = ["node_id", "uptime"]
        if not all(field in message for field in required_fields):
            return False
        if not isinstance(message.get("node_id"), str) or not message["node_id"].strip():
            return False
        if not isinstance(message.get("uptime"), (int, float)):
            return False
        return True

    @staticmethod
    def _extract_node_id(topic: str) -> str:
        parts = [part for part in topic.split("/") if part]
        return parts[-2] if len(parts) >= 2 else "unknown"
