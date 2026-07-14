#!/usr/bin/env bash
# Start the harness MCP server (macOS/Linux). Reads .env in the repo root.
set -e
cd "$(dirname "$0")/.."
python -m harness serve
