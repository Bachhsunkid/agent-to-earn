#!/bin/sh
# Deploy one commit of origin/main on the VM. Called by GitHub Actions over SSH:
#   ssh deploy@vm <40-hex commit sha>
# The deploy key's authorized_keys entry forces `sudo agent-to-earn-deploy "$SSH_ORIGINAL_COMMAND"`,
# so this script is the only thing that key can run. scripts/setup_deploy_user.sh installs a
# root-owned copy in /usr/local/bin; the repo copy is never executed with root rights.
set -eu

REPO="@REPO@"
sha="${1:-}"

fail() { echo "deploy refused: $*" >&2; exit 1; }

echo "$sha" | grep -Eq '^[0-9a-f]{40}$' || fail "expected a 40-hex commit sha, got '$sha'"
cd "$REPO"

git fetch --quiet origin main
git merge-base --is-ancestor "$sha" origin/main || fail "$sha is not on origin/main"

# Gate promotions edit tracked files on this machine; never overwrite them silently.
changes="$(git status --porcelain --untracked-files=no)"
[ -z "$changes" ] || fail "local changes to tracked files, commit them from the VM first:
$changes"

# Recreating the research container mid-run would kill the loop and leave a half-written journal.
[ ! -e agent/runs/.loop.lock ] || fail "research loop is running (agent/runs/.loop.lock), retry later"

old="$(git rev-parse HEAD)"
git merge --ff-only --quiet "$sha"
echo "checked out $(git log --oneline -1)"

# `up -d` recreates a service only when its compose config changes. These services run code
# mounted from the repo, so restart the ones whose files changed in this deploy.
changed="$(git diff --name-only "$old" HEAD)"
restart=""
touched() { echo "$changed" | grep -Eq "$1"; }
touched '^(dashboard/|agent/[^/]+\.py$)' && restart="$restart dashboard"
touched '^public/app\.py$' && restart="$restart public"
touched '^(user_data/config[^/]*\.json|user_data/strategies/(guarded_strategy\.py|live/)|docker/bot-entrypoint\.sh)' \
  && restart="$restart freqtrade"
touched '^agent/scheduler\.sh$' && restart="$restart research"

chown -R 1000:1000 user_data agent
docker compose up -d --build --remove-orphans
if [ -n "$restart" ]; then
  echo "restarting:$restart"
  # $restart is intentionally unquoted: a list of service names.
  docker compose restart $restart
fi

# Give containers a moment to crash if they are going to.
sleep 20
docker compose ps -a --format '{{.Service}}\t{{.State}}\t{{.Status}}'
bad="$(docker compose ps -a --format '{{.Service}} {{.State}}' | grep -v ' running$' || true)"
[ -z "$bad" ] || fail "services not running after deploy:
$bad"
echo "deploy ok"
