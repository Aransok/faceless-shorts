#!/usr/bin/env bash
# CHROME_PATH target for motionmaxxing renders in GitHub Actions.
# Runs @sparticuz/chromium without the runner proxy and with the flags a sandboxless CI box needs.
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHROME_BIN="$(node "$ROOT/scripts/chromium_path.cjs")"
exec "$CHROME_BIN" --no-sandbox --no-zygote --disable-dev-shm-usage --no-proxy-server --disable-gpu "$@"
