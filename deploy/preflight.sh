#!/usr/bin/env bash
# Read-only host checks. Run on the ITX PC: bash deploy/preflight.sh
set -eu
printf 'Architecture: '
uname -m
if [ "$(uname -m)" != x86_64 ]; then
  printf 'Expected 64-bit x86_64; verify the installed OS architecture.\n' >&2
  exit 1
fi
printf '\nMemory\n'
free -h
printf '\nProject disk\n'
df -h .
printf '\nClock synchronization\n'
timedatectl status
printf '\nDocker\n'
docker --version
docker compose version
docker info --format '{{.Architecture}}'
