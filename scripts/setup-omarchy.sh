#!/usr/bin/env bash
# Setup agent-apunts on Omarchy (Arch Linux). Safe to re-run (idempotent).
# Usage (from an existing clone):  bash scripts/setup-omarchy.sh
# Usage (fresh machine): see docs/SETUP.md
# Options: DIR=<path> (default: ~/code/agent-apunts)   WITH_OLLAMA=1 (only on a machine with a GPU)
set -euo pipefail

REPO="ignasicrespi11/agent-apunts"
DIR="${DIR:-$HOME/code/agent-apunts}"
step() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }
warn() { printf '\033[33m  %s\033[0m\n' "$1"; }

step "Installing packages with pacman"
pkgs=(git github-cli uv docker docker-compose docker-buildx)
[[ "${WITH_OLLAMA:-0}" == "1" ]] && pkgs+=(ollama)
sudo pacman -S --needed --noconfirm "${pkgs[@]}"

step "VS Code (Microsoft build: needed for the Dev Containers extension)"
if command -v code >/dev/null; then
  echo "  code already installed"
elif command -v yay >/dev/null; then
  yay -S --needed --noconfirm visual-studio-code-bin
else
  warn "yay not found: install 'visual-studio-code-bin' from the AUR manually"
fi

step "Docker service and group"
sudo systemctl enable --now docker.service
if ! id -nG "$USER" | grep -qw docker; then
  sudo usermod -aG docker "$USER"
  warn "Added $USER to the 'docker' group: log out and back in (or reboot) before using docker without sudo."
fi

step "Git identity"
git config --global user.name  >/dev/null || git config --global user.name  "$(read -rp '  Your full name for commits: ' v; echo "$v")"
git config --global user.email >/dev/null || git config --global user.email "$(read -rp '  Your GitHub email: ' v; echo "$v")"
git config --global init.defaultBranch main

step "GitHub login"
gh auth status >/dev/null 2>&1 || gh auth login --hostname github.com --git-protocol https --web

step "Repository"
if [[ -d "$DIR/.git" ]]; then
  echo "  Already cloned at $DIR"; git -C "$DIR" pull --ff-only
else
  mkdir -p "$(dirname "$DIR")"; gh repo clone "$REPO" "$DIR"
fi
git -C "$DIR" config core.hooksPath .githooks
echo "  Pre-commit hook enabled (blocks committing course material)"

step "Python 3.12 via uv"
uv python install 3.12
uv run --python 3.12 --no-project python --version

step "Local config"
[[ -f "$DIR/.env" ]] || { cp "$DIR/.env.example" "$DIR/.env"; echo "  Created .env (fill it in later)"; }
mkdir -p "$DIR/notes"

step "Docker check"
if docker info >/dev/null 2>&1; then echo "  Docker is running"; else warn "Docker not usable yet (log out/in for the group change)."; fi

step "Done"
echo "  Open the project: code \"$DIR\"  (VS Code will offer 'Reopen in Container' once the devcontainer exists)"
echo "  Copy your PDFs into $DIR/notes/<subject>/<doc_type>/ (they are never committed)"
