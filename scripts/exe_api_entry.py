from __future__ import annotations

import os
import uvicorn

from backend.app.main import app


def main() -> None:
    host = os.environ.get("KALSHI_BOT_HOST", "127.0.0.1")
    port_raw = os.environ.get("KALSHI_BOT_PORT", "8765")
    try:
        port = int(port_raw)
    except ValueError:
        port = 8765
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()