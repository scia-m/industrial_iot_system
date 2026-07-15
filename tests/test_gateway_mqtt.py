import json
import os
import tempfile
import unittest

from gateway.database import GatewayDatabase
from gateway.mqtt import MQTTGatewayService


class MQTTGatewayServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "gateway.db")
        self.db = GatewayDatabase(self.db_path)
        self.db.initialize()
        self.service = MQTTGatewayService(db=self.db)

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_processes_telemetry_and_heartbeat(self):
        telemetry_message = {
            "schema": "1.0",
            "node_id": "node_environment",
            "type": "telemetry",
            "timestamp": 1712345678,
            "payload": {"temperature_c": 22.7, "humidity_pct": 43.3},
        }
        heartbeat_message = {
            "node_id": "node_environment",
            "uptime": 1234,
            "free_heap": 182344,
            "wifi_rssi": -58,
            "firmware": "1.0.0",
        }
        status_message = {"status": "online"}

        self.service.handle_message("factory/node_environment/telemetry", json.dumps(telemetry_message))
        self.service.handle_message("factory/node_environment/heartbeat", json.dumps(heartbeat_message))
        self.service.handle_message("factory/node_environment/status", json.dumps(status_message))

        device = self.db._connect().execute("SELECT node_id, firmware, status, rssi FROM Devices WHERE node_id = ?", ("node_environment",)).fetchone()
        self.assertEqual(device[0], "node_environment")
        self.assertEqual(device[1], "1.0.0")
        self.assertEqual(device[2], "online")
        self.assertEqual(device[3], -58)

        measurements = self.db._connect().execute("SELECT node_id, measurement_type, value FROM Measurements ORDER BY id").fetchall()
        self.assertEqual(len(measurements), 2)
        self.assertEqual(measurements[0][1], "temperature_c")
        self.assertEqual(measurements[0][2], 22.7)
        self.assertEqual(measurements[1][1], "humidity_pct")
        self.assertEqual(measurements[1][2], 43.3)

        heartbeats = self.db._connect().execute("SELECT node_id, uptime, free_heap, wifi_rssi, firmware FROM Heartbeats").fetchall()
        self.assertEqual(len(heartbeats), 1)
        self.assertEqual(heartbeats[0][1], 1234)

        events = self.db._connect().execute("SELECT event_type, message FROM Events ORDER BY id").fetchall()
        self.assertTrue(any(event[0] == "telemetry_received" for event in events))
        self.assertTrue(any(event[0] == "heartbeat_received" for event in events))
        self.assertTrue(any(event[0] == "status_received" for event in events))


if __name__ == "__main__":
    unittest.main()
