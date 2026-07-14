#!/usr/bin/env bash
# Expose the local harness to ChatGPT via Tailscale Funnel and print the MCP URL.
# Usage:  ./scripts/funnel.sh [port]
set -e
cd "$(dirname "$0")/.."
PORT="${1:-8848}"
echo "Starting Tailscale Funnel for local port $PORT ..."
tailscale funnel --bg "$PORT"
tailscale funnel status
echo
echo "Paste this MCP URL into the ChatGPT connector:"
python -m harness url
