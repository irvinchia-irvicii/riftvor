#!/bin/zsh
# run_nightly.sh — Riftvor nightly heartbeat (port of the 3vor Fetch
# pattern): forced sync for history continuity + watchlist email check +
# weekly dormant-store poll. Wire into launchd with install_nightly.command.
cd "$(dirname "$0")"
mkdir -p state
venv/bin/python nightly.py >> state/nightly.log 2>&1
