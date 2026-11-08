#!/usr/bin/env bash
# Stream the project from GitHub to the VPS. GitHub authentication stays on the Mac.
set -euo pipefail
repo=apicodeboy/link-downloader-org
# This branch contains the native installer and the pinned application revision.
ref=hostinger-vps-78e4ea79
server=${VPS_SSH_USER:-root}@2.25.142.128
port=${VPS_SSH_PORT:-22}
control=$(mktemp -d)
sock=$control/ssh
conn=(ssh -o "ControlPath=$sock" -p "$port")
remote=''
cleanup() {
    if [[ "$remote" =~ ^/tmp/linkdownloader\.[A-Za-z0-9]+$ ]]; then
        "${conn[@]}" -o BatchMode=yes "$server" "rm -rf -- '$remote'" </dev/null 2>/dev/null || true
    fi
    "${conn[@]}" -O exit "$server" </dev/null 2>/dev/null || true
    rm -rf -- "$control"
}
trap cleanup EXIT
gh auth status --hostname github.com >/dev/null || { echo 'Run gh auth login on your Mac and try again.'; exit 1; }
sha=$(gh api "repos/$repo/commits/$ref" --jq '.sha')
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || { echo 'GitHub did not return a commit.'; exit 1; }
echo "Sending private release source to $server through SSH."
"${conn[@]}" -o ControlMaster=yes -o ControlPersist=120 -Nf "$server"
remote=$("${conn[@]}" "$server" 'umask 077; mktemp -d /tmp/linkdownloader.XXXXXXXXXX')
[[ "$remote" =~ ^/tmp/linkdownloader\.[A-Za-z0-9]+$ ]] || { echo 'Unexpected temporary directory.'; exit 1; }
gh api "repos/$repo/tarball/$sha" | "${conn[@]}" "$server" "umask 077; tar --strip-components=1 --no-same-owner -xz -C '$remote'"
"${conn[@]}" -t "$server" "cd '$remote' && sudo -- bash deploy/hostinger/install-native.sh"
