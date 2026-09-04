#!/usr/bin/env bash
# One-time host setup for the agent box. Requires sudo -- run this yourself
# interactively (it needs your password), not via an automated tool.
#
# Installs: docker-compose-plugin, nvidia-container-toolkit; configures the
# nvidia Docker runtime; restarts docker.
set -euo pipefail

echo "== Installing docker-compose-plugin =="
sudo apt-get update
sudo apt-get install -y docker-compose-plugin

echo "== Installing nvidia-container-toolkit =="
if ! command -v nvidia-ctk >/dev/null 2>&1; then
  distribution=$(. /etc/os-release; echo "$ID$VERSION_ID")
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
    | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
    | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
  sudo apt-get update
  sudo apt-get install -y nvidia-container-toolkit
fi

echo "== Configuring nvidia Docker runtime =="
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

echo "== Verifying GPU is visible inside a container =="
docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu24.04 nvidia-smi

echo "== Done. GPU containers are ready. =="
