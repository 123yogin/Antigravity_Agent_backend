#!/bin/bash

echo "======================================================="
echo "   🛡️ NATIVE DOCKER ENGINE INSTALLER (WSL/UBUNTU) 🛡️"
echo "======================================================="
echo ""

# 1. Update system
echo "[1/5] Updating system packages..."
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg

# 2. Add Docker's official GPG key
echo "[2/5] Adding Docker GPG key..."
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# 3. Set up the repository
echo "[3/5] Setting up Docker repository..."
echo \
  "deb [arch="$(dpkg --print-architecture)" signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  "$(. /etc/os-release && echo "$VERSION_CODENAME")" stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# 4. Install Docker Engine
echo "[4/5] Installing Docker Engine & Compose..."
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 5. Post-install setup
echo "[5/5] Configuring permissions..."
sudo usermod -aG docker $USER
sudo service docker start

echo ""
echo "======================================================="
echo "   ✅ NATIVE DOCKER INSTALLED SUCCESSFULLY!"
echo "======================================================="
echo "IMPORTANT: Please close this terminal and open a new one"
echo "to apply the group changes. Then run ./start.sh"
echo "======================================================="
