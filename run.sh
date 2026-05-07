#!/bin/bash
set -e

cd "$(dirname "$0")"

# Allow OAuth over plain HTTP in development
export OAUTHLIB_INSECURE_TRANSPORT=1

if [ ! -f backend/.venv/bin/activate ]; then
  echo "Creating virtual environment..."
  python3 -m venv backend/.venv
fi

source backend/.venv/bin/activate

echo "Installing dependencies..."
pip install -q -r backend/requirements.txt

if [ ! -f .env ]; then
  echo ""
  echo "⚠  No .env file found. Copy .env.example and fill in your Google credentials:"
  echo "   cp .env.example .env"
  echo ""
  exit 1
fi

echo ""
echo "Starting server at http://localhost:8000"
echo ""

cd backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
