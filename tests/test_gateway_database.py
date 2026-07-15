import os
import sqlite3
import tempfile
import unittest

from gateway.database import GatewayDatabase


class GatewayDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "gateway.db")
        self.db = GatewayDatabase(self.db_path)

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_schema_and_device_flow(self):
        self.db.initialize()

        self.db.register_device(
            node_id="node_environment",
            firmware="1.0.0",
            status="ok",
            rssi=-58,
        )

        self.db.record_heartbeat(
            node_id="node_environment",
            uptime=1234,
            free_heap=182344,
            wifi_rssi=-58,
            firmware="1.0.0",
            status="ok",
        )

        self.db.record_measurement(
            node_id="node_environment",
            measurement_type="temperature",
            value=21.7,
            unit="C",
            metadata={"sensor": "bme280"},
        )

        self.db.record_event(node_id="node_environment", event_type="heartbeat", message="heartbeat received")
        self.db.record_command(node_id="node_environment", command="reboot", payload="{}")
        self.db.record_firmware_version(node_id="node_environment", version="1.0.0", notes="initial release")

        with sqlite3.connect(self.db_path) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            self.assertTrue({"Devices", "Measurements", "Heartbeats", "Events", "Commands", "FirmwareVersions"}.issubset(tables))

            device = conn.execute("SELECT node_id, firmware, status, rssi FROM Devices WHERE node_id = ?", ("node_environment",)).fetchone()
            self.assertEqual(device[0], "node_environment")
            self.assertEqual(device[1], "1.0.0")
            self.assertEqual(device[2], "ok")
            self.assertEqual(device[3], -58)

            measurement = conn.execute("SELECT node_id, measurement_type, value, unit FROM Measurements WHERE node_id = ?", ("node_environment",)).fetchone()
            self.assertEqual(measurement[0], "node_environment")
            self.assertEqual(measurement[1], "temperature")
            self.assertEqual(measurement[2], 21.7)
            self.assertEqual(measurement[3], "C")

            heartbeat = conn.execute("SELECT node_id, uptime, free_heap, wifi_rssi, firmware FROM Heartbeats WHERE node_id = ?", ("node_environment",)).fetchone()
            self.assertEqual(heartbeat[1], 1234)
            self.assertEqual(heartbeat[2], 182344)
            self.assertEqual(heartbeat[3], -58)
            self.assertEqual(heartbeat[4], "1.0.0")

            command = conn.execute("SELECT node_id, command, payload FROM Commands WHERE node_id = ?", ("node_environment",)).fetchone()
            self.assertEqual(command[1], "reboot")
            self.assertEqual(command[2], "{}")

            firmware_version = conn.execute("SELECT node_id, version, notes FROM FirmwareVersions WHERE node_id = ?", ("node_environment",)).fetchone()
            self.assertEqual(firmware_version[1], "1.0.0")
            self.assertEqual(firmware_version[2], "initial release")


if __name__ == "__main__":
    unittest.main()
