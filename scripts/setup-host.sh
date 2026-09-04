#!/usr/bin/env bash
# One-time host setup for the agent box. Requires sudo -- run this yourself
# interactively (it needs your password), not via an automated tool.
#
# Installs: docker-compose-plugin, nvidia-container-toolkit; configures the
# nvidia Docker runtime; restarts docker.
set -euo pipefail

echo "== Installing the docker compose plugin =="
sudo apt-get update
# Docker was installed here via Ubuntu's docker.io package, not Docker's own
# apt repo -- so it's docker-compose-v2, not docker-compose-plugin.
if apt-cache policy docker-compose-plugin 2>/dev/null | grep -q Candidate:.*[0-9]; then
  sudo apt-get install -y docker-compose-plugin
else
  sudo apt-get install -y docker-compose-v2
fi

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

echo "== Adding $USER to the docker group (so docker commands don't need sudo) =="
if ! groups "$USER" | grep -qw docker; then
  sudo usermod -aG docker "$USER"
  echo "Group added. You must log out and back in (or run 'newgrp docker' in this"
  echo "shell) before the group change takes effect."
  NEWGRP_NEEDED=1
fi

echo "== Verifying GPU is visible inside a container =="
if [ "${NEWGRP_NEEDED:-0}" = "1" ]; then
  sudo docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu24.04 nvidia-smi
else
  docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu24.04 nvidia-smi
fi

echo "== Done. GPU containers are ready. =="
[ "${NEWGRP_NEEDED:-0}" = "1" ] && echo "Remember: log out/in (or 'newgrp docker') before running docker compose without sudo."
