#!/usr/bin/env bash
# Weekly refresh for every league in leagues/: fetch the current season from ESPN, rebuild, audit, redraw the page,
# share cards and offline files. A league whose audit fails is put back the way it was (the others still update),
# and the script exits non-zero at the end so GitHub emails the repo owner.
# Env: FORCE=true rebuilds even if ESPN's data hasn't changed. Writes the changed leagues to changed_leagues.txt.
set -uo pipefail
: > changed_leagues.txt
failed=0
season=$(python3 -c "import datetime as d; n = d.date.today(); print(n.year if n.month >= 8 else n.year - 1)")
for cfg in leagues/*.json; do
  dir=$(python3 -c "import json; print(json.load(open('$cfg'))['site']['dir'] or '.')")
  name=$(python3 -c "import json; print(json.load(open('$cfg'))['name'])")
  echo "::group::$name"
  if [ -f "$dir/raw/$season.json" ] && python3 -c "import json, sys; sys.exit(0 if json.load(open('$dir/raw/$season.json'))['done'] else 1)"; then
    echo "$season is already final."
  elif ! python3 pipeline/fetch_season.py "$cfg" "$season"; then
    echo "::error::$name: ESPN fetch failed (cookies expired?)"; failed=1; echo "::endgroup::"; continue
  fi
  if [ -z "$(git status --porcelain "$dir/raw")" ] && [ "${FORCE:-false}" != "true" ]; then
    echo "No new ESPN data."
    python3 pipeline/replay_archive.py "$cfg" || echo "::warning::$name: replay not saved"
    [ -n "$(git status --porcelain "$dir/replays")" ] && echo "$cfg" >> changed_leagues.txt
    echo "::endgroup::"; continue
  fi
  if python3 pipeline/build.py "$dir/raw" "$dir/data.json" "$cfg" && python3 audit/audit.py "$dir/raw" "$dir/data.json" "$cfg" | tail -25; then
    python3 pipeline/replay_archive.py "$cfg" || echo "::warning::$name: replay not saved"
    python3 pipeline/page.py "$cfg"
    python3 pipeline/cards.py "$cfg" || echo "::warning::$name: share cards were not redrawn"
    python3 pipeline/summary.py "$dir/data.json" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
    echo "$cfg" >> changed_leagues.txt
  else
    echo "::error::$name: build or audit failed; this league was left as it was"
    git checkout -- "$dir/raw" "$dir/data.json" 2>/dev/null; failed=1
  fi
  echo "::endgroup::"
done
exit $failed
