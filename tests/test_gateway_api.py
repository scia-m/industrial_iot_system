import os
import tempfile
import unittest

from fastapi.testclient import TestClient

import gateway.api.app as api_app
from gateway.database import GatewayDatabase


class GatewayAPITests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "gateway.db")
        self.db = GatewayDatabase(self.db_path)
        self.db.initialize()
        self.db.register_device(node_id="node_environment", firmware="1.0.0", status="ok", rssi=-58)
        self.db.record_measurement(node_id="node_environment", measurement_type="temperature_c", value=22.7, unit="C")
        self.db.record_event(node_id="node_environment", event_type="telemetry_received", message="Telemetry received")
        api_app.db = self.db
        self.client = TestClient(api_app.app)

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_api_endpoints(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

        response = self.client.get("/devices")
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.json()), 1)

        response = self.client.get("/devices/node_environment")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["node_id"], "node_environment")

        response = self.client.get("/devices/node_environment/measurements")
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.json()), 1)

        response = self.client.get("/devices/node_environment/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

        response = self.client.get("/events")
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.json()), 1)

        response = self.client.post(
            "/commands",
            json={"node_id": "node_environment", "command": "reboot", "payload": {"delay": 5}},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "queued")


if __name__ == "__main__":
    unittest.main()
