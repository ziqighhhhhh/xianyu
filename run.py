"""Development entrypoint for the FishAutoPro clone.

Usage:
    python run.py            # http://127.0.0.1:8000
    FAP_HOST=0.0.0.0 FAP_PORT=9000 python run.py
"""

from __future__ import annotations

import os

from fap import create_app

app = create_app()

if __name__ == "__main__":
    host = os.environ.get("FAP_HOST", "127.0.0.1")
    port = int(os.environ.get("FAP_PORT", "8000"))
    app.run(host=host, port=port, debug=False, threaded=True)
