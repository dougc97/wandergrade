#!/usr/bin/env bash
# Start the dashboard. Usage: ./run.sh [port]
cd "$(dirname "$0")" || exit 1
exec python3 server.py "${1:-8000}"
