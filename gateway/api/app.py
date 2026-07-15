import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from gateway.database import GatewayDatabase

app = FastAPI(title="Industrial IoT Gateway API")

DEFAULT_DB_PATH = os.getenv("GATEWAY_DB_PATH", "gateway/gateway.db")
db = GatewayDatabase(DEFAULT_DB_PATH)
db.initialize()
DASHBOARD_PATH = Path(__file__).resolve().parents[1] / "dashboard" / "index.html"


class CommandRequest(BaseModel):
    node_id: str = Field(..., min_length=1)
    command: str = Field(..., min_length=1)
    payload: Optional[Dict[str, Any]] = None


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    if DASHBOARD_PATH.exists():
        return HTMLResponse(DASHBOARD_PATH.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Dashboard not found</h1>", status_code=404)


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/devices")
def list_devices() -> List[Dict[str, Any]]:
    rows = db._connect().execute(
        "SELECT node_id, first_seen, last_seen, firmware, status, rssi FROM Devices ORDER BY last_seen DESC"
    ).fetchall()
    return [
        {
            "node_id": row["node_id"],
            "first_seen": row["first_seen"],
            "last_seen": row["last_seen"],
            "firmware": row["firmware"],
            "status": row["status"],
            "rssi": row["rssi"],
        }
        for row in rows
    ]


@app.get("/devices/{node_id}")
def get_device(node_id: str) -> Dict[str, Any]:
    row = db._connect().execute(
        "SELECT node_id, first_seen, last_seen, firmware, status, rssi FROM Devices WHERE node_id = ?",
        (node_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="device not found")
    return {
        "node_id": row["node_id"],
        "first_seen": row["first_seen"],
        "last_seen": row["last_seen"],
        "firmware": row["firmware"],
        "status": row["status"],
        "rssi": row["rssi"],
    }


@app.get("/devices/{node_id}/measurements")
def get_measurements(node_id: str, limit: int = Query(default=50, ge=1, le=200)) -> List[Dict[str, Any]]:
    rows = db._connect().execute(
        "SELECT node_id, measurement_type, value, unit, metadata, created_at FROM Measurements WHERE node_id = ? ORDER BY id DESC LIMIT ?",
        (node_id, limit),
    ).fetchall()
    return [
        {
            "node_id": row["node_id"],
            "measurement_type": row["measurement_type"],
            "value": row["value"],
            "unit": row["unit"],
            "metadata": row["metadata"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


@app.get("/devices/{node_id}/status")
def get_status(node_id: str) -> Dict[str, Any]:
    row = db._connect().execute(
        "SELECT node_id, firmware, status, rssi, last_seen FROM Devices WHERE node_id = ?",
        (node_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="device not found")
    return {
        "node_id": row["node_id"],
        "firmware": row["firmware"],
        "status": row["status"],
        "rssi": row["rssi"],
        "last_seen": row["last_seen"],
    }


@app.get("/events")
def list_events(limit: int = Query(default=100, ge=1, le=200)) -> List[Dict[str, Any]]:
    rows = db._connect().execute(
        "SELECT id, node_id, event_type, message, created_at FROM Events ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "node_id": row["node_id"],
            "event_type": row["event_type"],
            "message": row["message"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


@app.post("/commands")
def send_command(command: CommandRequest) -> Dict[str, Any]:
    db.record_command(node_id=command.node_id, command=command.command, payload=str(command.payload or {}))
    return {
        "node_id": command.node_id,
        "command": command.command,
        "payload": command.payload,
        "status": "queued",
    }
