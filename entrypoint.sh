#!/bin/bash
set -e

echo "Running database migrations..."
flask db upgrade

echo "Initializing admin users..."
flask init-users

echo ""
echo "================================"
echo "Starting Gunicorn..."
echo "App running at: http://localhost:5000"
echo "================================"
echo ""
exec python -m gunicorn --bind 0.0.0.0:5000 app:app