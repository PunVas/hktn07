#!/bin/bash

set -e

echo "======================================"
echo "Starting PR Guardian Local Environment"
echo "======================================"

# Activate virtual environment
if [ ! -d "venv" ]; then
    echo "❌ venv not found."
    echo "Create it first:"
    echo "python3 -m venv venv"
    exit 1
fi

source venv/bin/activate

# Start PostgreSQL
echo "Starting PostgreSQL..."
brew services start postgresql@16 >/dev/null 2>&1 || true

# Start Redis
echo "Starting Redis..."
brew services start redis >/dev/null 2>&1 || true

# Export local environment variables
export DATABASE_URL="postgresql+psycopg2://prguardian:prguardian@localhost:5432/prguardian"
export REDIS_URL="redis://localhost:6379/0"

# Load additional env vars if .env exists
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
fi

# Start RQ worker in background
echo "Starting worker..."
python -m app.workers.rq_worker &
WORKER_PID=$!

# Cleanup on exit
cleanup() {
    echo ""
    echo "Stopping worker..."
    kill $WORKER_PID 2>/dev/null || true
    exit
}

trap cleanup SIGINT SIGTERM EXIT

echo ""
echo "======================================"
echo "Backend: http://localhost:8000"
echo "Worker PID: $WORKER_PID"
echo "======================================"
echo ""

# Start FastAPI
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000