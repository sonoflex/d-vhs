#!/bin/bash

echo "Running database migrations..."
flask db upgrade 2>/dev/null || echo "No migrations yet"

echo "Initializing admin users..."
flask init-users 2>/dev/null || echo "Could not initialize users"

echo ""
echo "================================"
echo "Starting Gunicorn..."
echo "App running at: http://localhost:5000"
echo "================================"
echo ""
exec python -m gunicorn --bind 0.0.0.0:5000 app:app