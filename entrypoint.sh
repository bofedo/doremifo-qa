#!/bin/sh
pip install psycopg2-binary --quiet
exec uvicorn app:app --host 0.0.0.0 --port 8000
