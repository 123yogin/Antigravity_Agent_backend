#!/bin/bash

echo "======================================================="
echo "   ⚡ ANTIGRAVITY OPERATOR - LINUX/WSL LAUNCHER ⚡"
echo "======================================================="
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "[ERROR] Docker is not running!"
    echo "Please start Docker or Docker Desktop and try again."
    exit 1
fi

echo "[1/3] Building containers and pulling AI models..."
echo "[INFO] This might take a few minutes on first run."
echo ""

docker-compose up --build -d

echo ""
echo "======================================================="
echo "   ✅ SYSTEM ONLINE!"
echo "======================================================="
echo ""
echo "Dashboard: http://localhost:3000"
echo "Backend API: http://localhost:8000"
echo "Ollama API:  http://localhost:11434"
echo ""
echo "To see live logs, type: docker-compose logs -f"
echo "To stop the system, run: ./stop.sh"
echo "======================================================="
