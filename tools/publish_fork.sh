#!/usr/bin/env bash
# Publish this patched tree to your own GitHub fork of
# ussy1995/home-assistant-yorkshire-water, so HACS can install it.
#
#   ./tools/publish_fork.sh <your-github-username>
#
# Steps it does for you:
#   1. points "fork" at your fork
#   2. pushes the current branch
#
# Fork first (GitHub web UI):
#   https://github.com/ussy1995/home-assistant-yorkshire-water/fork
#
# GitHub no longer accepts a password for git over HTTPS. Use a personal
# access token (classic, scope: repo) as the password, or a fine-grained token
# with write access to that repository.

set -euo pipefail

USER_NAME="${1:-}"
if [[ -z "$USER_NAME" ]]; then
  echo "usage: $0 <your-github-username>" >&2
  exit 2
fi

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FORK_URL="https://github.com/${USER_NAME}/home-assistant-yorkshire-water.git"

cd "$REPO_DIR"

if [[ ! -d .git ]]; then
  echo "not a git repository: $REPO_DIR" >&2
  exit 1
fi

if git remote get-url fork >/dev/null 2>&1; then
  git remote set-url fork "$FORK_URL"
else
  git remote add fork "$FORK_URL"
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
echo "pushing branch '$BRANCH' to $FORK_URL"
git push -u fork "$BRANCH"

cat <<EOF

Done. The fork now carries the fix.

Next:
  1. Tell me the fork name (${USER_NAME}/home-assistant-yorkshire-water) so I
     can point HACS at it, install it and reload the integration.
  2. Optionally tag a release so HACS can install a version:
       git -C "$REPO_DIR" tag v1.1.0 && git -C "$REPO_DIR" push fork v1.1.0
EOF
