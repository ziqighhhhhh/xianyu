"""Production entrypoint using waitress.

    python serve.py
"""

from __future__ import annotations

import os

from waitress import serve

from fap import create_app

app = create_app()

if __name__ == "__main__":
    host = os.environ.get("FAP_HOST", "127.0.0.1")
    port = int(os.environ.get("FAP_PORT", "8000"))
    threads = int(os.environ.get("FAP_THREADS", "8"))
    serve(app, host=host, port=port, threads=threads)
