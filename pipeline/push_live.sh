#!/usr/bin/env bash
# Publish the live snapshots (LIVE_DIR/*.json) as the single commit on the `live` branch.
# Overwritten every time, so game days add no history to main and don't rebuild the site.
set -e
cd "$LIVE_DIR"
exec 9>/tmp/push_live.lock; flock 9
rm -rf .git
git init -q -b live
git add -A
git -c user.name="brown-cow-bot" -c user.email="41898282+github-actions[bot]@users.noreply.github.com" commit -q -m "Live $(date -u +%H:%M) UTC"
git push -q -f "https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git" live
