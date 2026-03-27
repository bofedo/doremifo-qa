#!/bin/sh
echo "DEBUG: DOREMIFO_KEY=${DOREMIFO_KEY}"
export DOREMIFO_KEY="${DOREMIFO_KEY}"
exec uvicorn app:app --host 0.0.0.0 --port 8000
