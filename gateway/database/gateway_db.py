import json
import sqlite3
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Dict, Optional


class GatewayDatabase:
    """SQLite-backed database layer for the gateway."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path or "gateway/gateway.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self) -> None:
        conn = self._connect()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS Devices (
                node_id TEXT PRIMARY KEY,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                firmware TEXT,
                status TEXT NOT NULL,
                rssi INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS Measurements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id TEXT NOT NULL,
                measurement_type TEXT NOT NULL,
                value REAL NOT NULL,
                unit TEXT,
                metadata TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(node_id) REFERENCES Devices(node_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS Heartbeats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id TEXT NOT NULL,
                uptime INTEGER NOT NULL,
                free_heap INTEGER,
                wifi_rssi INTEGER,
                firmware TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(node_id) REFERENCES Devices(node_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS Events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id TEXT,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS Commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id TEXT NOT NULL,
                command TEXT NOT NULL,
                payload TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(node_id) REFERENCES Devices(node_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS FirmwareVersions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id TEXT NOT NULL,
                version TEXT NOT NULL,
                notes TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(node_id) REFERENCES Devices(node_id)
            )
            """
        )
        conn.commit()
        conn.close()

    def register_device(
        self,
        node_id: str,
        firmware: Optional[str] = None,
        status: Optional[str] = None,
        rssi: Optional[int] = None,
    ) -> None:
        now = self._timestamp()
        conn = self._connect()
        existing = conn.execute("SELECT node_id FROM Devices WHERE node_id = ?", (node_id,)).fetchone()
        if existing:
            update_fields = ["last_seen = ?"]
            update_values: list[Any] = [now]
            if firmware is not None:
                update_fields.append("firmware = ?")
                update_values.append(firmware)
            if status is not None:
                update_fields.append("status = ?")
                update_values.append(status)
            if rssi is not None:
                update_fields.append("rssi = ?")
                update_values.append(rssi)
            update_values.append(node_id)
            conn.execute(
                f"UPDATE Devices SET {', '.join(update_fields)} WHERE node_id = ?",
                update_values,
            )
        else:
            insert_status = status or "unknown"
            conn.execute(
                """
                INSERT INTO Devices(node_id, first_seen, last_seen, firmware, status, rssi)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (node_id, now, now, firmware, insert_status, rssi),
            )
        conn.commit()
        conn.close()

    def record_measurement(
        self,
        node_id: str,
        measurement_type: str,
        value: float,
        unit: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.register_device(node_id=node_id)
        conn = self._connect()
        conn.execute(
            """
            INSERT INTO Measurements(node_id, measurement_type, value, unit, metadata, created_at)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            (
                node_id,
                measurement_type,
                float(value),
                unit,
                json.dumps(metadata or {}, ensure_ascii=False),
                self._timestamp(),
            ),
        )
        conn.commit()
        conn.close()

    def record_heartbeat(
        self,
        node_id: str,
        uptime: int,
        free_heap: Optional[int] = None,
        wifi_rssi: Optional[int] = None,
        firmware: Optional[str] = None,
        status: str = "unknown",
    ) -> None:
        self.register_device(node_id=node_id, firmware=firmware, status=status, rssi=wifi_rssi)
        conn = self._connect()
        conn.execute(
            """
            INSERT INTO Heartbeats(node_id, uptime, free_heap, wifi_rssi, firmware, created_at)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            (node_id, uptime, free_heap, wifi_rssi, firmware, self._timestamp()),
        )
        conn.commit()
        conn.close()

    def record_event(self, node_id: Optional[str], event_type: str, message: str) -> None:
        conn = self._connect()
        conn.execute(
            """
            INSERT INTO Events(node_id, event_type, message, created_at)
            VALUES(?, ?, ?, ?)
            """,
            (node_id, event_type, message, self._timestamp()),
        )
        conn.commit()
        conn.close()

    def record_command(self, node_id: str, command: str, payload: Optional[str] = None) -> None:
        self.register_device(node_id=node_id)
        conn = self._connect()
        conn.execute(
            """
            INSERT INTO Commands(node_id, command, payload, created_at)
            VALUES(?, ?, ?, ?)
            """,
            (node_id, command, payload, self._timestamp()),
        )
        conn.commit()
        conn.close()

    def record_firmware_version(self, node_id: str, version: str, notes: Optional[str] = None) -> None:
        self.register_device(node_id=node_id)
        conn = self._connect()
        conn.execute(
            """
            INSERT INTO FirmwareVersions(node_id, version, notes, created_at)
            VALUES(?, ?, ?, ?)
            """,
            (node_id, version, notes, self._timestamp()),
        )
        conn.commit()
        conn.close()

    def close(self) -> None:
        return None

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(UTC).isoformat(timespec="seconds")
