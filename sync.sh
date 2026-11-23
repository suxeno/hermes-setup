#!/usr/bin/env bash
# Create a fresh local checkpoint; publish it only if explicitly requested.
set -euo pipefail
umask 077
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
slug=suxeno/hermes-setup
store=${HERMES_BACKUP_DIR:-$HOME/.local/share/hermes-setup}
key=${HERMES_BACKUP_KEY_FILE:-$store/setup.key}
units=${HERMES_UNITS_DIR:-$HOME/.config/systemd/user}
source_home=${HERMES_HOME:-$HOME/.hermes}

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
private_repo() {
    [[ $(gh api "repos/$slug" --jq '.visibility') == private ]] ||
        die 'Snapshot publication requires a verified private repo.'
}

case ${1:-} in
    '') publish=false ;;
    --publish) publish=true ;;
    *) die 'Usage: bash sync.sh [--publish]' ;;
esac
[[ $# -le 1 ]] || die 'Usage: bash sync.sh [--publish]'
cd -- "$repo"
python3 - "$repo" "$store" "$key" "$source_home" <<'PY'
from pathlib import Path
import sys
repo, store, key, home = (Path(x).resolve() for x in sys.argv[1:])
if any(p == repo or repo in p.parents for p in (store, key)):
    sys.exit('Backup storage and encryption key must be outside the checkout.')
if home.parent.name == 'profiles':
    sys.exit('Point HERMES_HOME at the manager home, not an individual profile.')
PY

if $publish; then
    [[ $(git remote get-url --push --all origin) == "https://github.com/$slug.git" ]] ||
        die 'Expected a single HTTPS push URL for origin: suxeno/hermes-setup.'
    [[ $(git symbolic-ref --short HEAD) == main && -z $(git status --porcelain) ]] ||
        die 'Publication requires a clean main checkout.'
    private_repo
    remote=$(gh api "repos/$slug/git/ref/heads/main" --jq '.object.sha')
    [[ "$(git rev-parse HEAD)" == "$remote" ]] || die 'Local main must match GitHub main before publishing.'
    git_identity=()
    if ! git var GIT_AUTHOR_IDENT >/dev/null 2>&1 || ! git var GIT_COMMITTER_IDENT >/dev/null 2>&1; then
        email=$(gh api user --jq '"\(.id)+\(.login)@users.noreply.github.com"')
        [[ "$email" =~ ^[0-9]+\+[A-Za-z0-9-]+@users\.noreply\.github\.com$ ]] || die 'Could not resolve a Git commit identity.'
        git_identity=(-c 'user.name=Hermes Agent' -c "user.email=$email")
    fi
fi

mkdir -p -- "$store"
if [[ ! -e "$key" ]]; then
    if $publish; then
        die 'Encryption key missing. Recover it from secure storage or first run local sync on a new setup.'
    fi
    python3 snapshot.py keygen "$key"
fi
stamp=$(python3 -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))')
archive="$store/setup-$stamp.tar.gz.gpg"
python3 snapshot.py backup --home "$source_home" --key-file "$key" --units-dir "$units" "$archive"

if $publish; then
    (( $(wc -c < "$archive") < 100 * 1024 * 1024 )) || die 'Snapshot exceeds GitHub file size limit.'
    private_repo
    [[ ! -L backup && ! -L backup/setup.tar.gz.gpg ]] || die 'Unexpected symlink in snapshot destination.'
    mkdir -p backup
    pending=$(mktemp backup/.setup.XXXXXXXX)
    trap 'rm -f -- "$pending"' EXIT
    cp -- "$archive" "$pending"
    mv -f -- "$pending" backup/setup.tar.gz.gpg
    git add -- backup/setup.tar.gz.gpg
    git "${git_identity[@]}" commit --only -m 'backup: refresh encrypted Hermes setup' -- backup/setup.tar.gz.gpg
    private_repo
    git -c credential.helper= -c 'credential.helper=!gh auth git-credential' push origin HEAD:refs/heads/main
    [[ "$(gh api "repos/$slug/git/ref/heads/main" --jq '.object.sha')" == "$(git rev-parse HEAD)" ]] ||
        die 'Could not verify the published GitHub revision.'
    printf 'Published and verified %s@%s\n' "$slug" "$(git rev-parse --short HEAD)"
fi
