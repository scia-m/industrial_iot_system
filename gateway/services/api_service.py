#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))


def load_config(path: str | None = None) -> dict:
    config_path = Path(path or os.getenv("API_SERVICE_CONFIG", str(ROOT / "services" / "api_config.json")))
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def run() -> None:
    config = load_config()
    host = config.get("host", "0.0.0.0")
    port = int(config.get("port", 8000))
    reload_mode = bool(config.get("reload", False))

    os.environ.setdefault("GATEWAY_DB_PATH", str(ROOT / "gateway.db"))

    import uvicorn
    from gateway.api.app import app

    uvicorn.run(app, host=host, port=port, reload=reload_mode)


if __name__ == "__main__":
    run()
