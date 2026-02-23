#!/bin/bash
set -e
PORT=${PORT:-8000}
exec python -m uvicorn api.main:app --host 0.0.0.0 --port "$PORT"
