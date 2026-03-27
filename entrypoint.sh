#!/bin/sh
echo "DEBUG: DOREMIFO_KEY=${DOREMIFO_KEY}"
exec env DOREMIFO_KEY="${DOREMIFO_KEY}" uvicorn app:app --host 0.0.0.0 --port 8000
