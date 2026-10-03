#!/usr/bin/env bash
# Run from anywhere after copying the complete transfer folder to Ubuntu.
set -eu
project_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$project_dir"
if [ "$(uname -m)" != x86_64 ]; then
  printf 'This bundle requires 64-bit Ubuntu (uname -m: x86_64).\n' >&2
  exit 1
fi
mkdir -p data
if [ ! -e config.local.json ]; then
  cp config.example.json config.local.json
  printf 'Created config.local.json. Replace sample entity IDs after discovery.\n'
fi
if [ ! -e safety-policy.local.json ]; then
  cp safety-policy.example.json safety-policy.local.json
  printf 'Created safety-policy.local.json with an empty device allowlist.\n'
fi
if ! command -v docker >/dev/null 2>&1; then
  printf 'Install Docker Engine and Compose first: https://docs.docker.com/engine/install/ubuntu/\n' >&2
  exit 1
fi
docker compose version
docker compose -f deploy/compose.yaml --profile tools config --quiet
printf '\nPreparation complete. Continue with START_HERE.md.\n'
