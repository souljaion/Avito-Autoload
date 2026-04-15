#!/bin/bash
set -e

cd /home/claude2/avito-autoload

echo "==> Pulling latest code..."
git pull origin main

echo "==> Installing dependencies..."
./venv/bin/pip install -r requirements.txt

echo "==> Running migrations..."
./venv/bin/alembic upgrade head

echo "==> Restarting service..."
sudo systemctl restart avito-autoload

echo "==> Waiting for startup..."
sleep 3

echo "==> Health check..."
curl -f http://localhost:8001/health && echo -e "\nDeploy OK" || echo "Deploy FAILED"
