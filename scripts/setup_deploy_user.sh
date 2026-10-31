#!/bin/sh
# One-time VM setup for GitHub Actions deploys. Run as root on the VM from the repo root:
#   sh scripts/setup_deploy_user.sh <public host or IP> [ssh port]
#
# Creates a `deploy` user whose only power is running the root-owned deploy script, generates
# its SSH key on the VM, and prints the values for the GitHub secrets. The private key is
# printed once and then deleted from the VM. Re-run after changing scripts/vm_deploy.sh to
# install the new version (the existing key is kept unless you pass --new-key).
set -eu

host="${1:?usage: sh scripts/setup_deploy_user.sh <public host or IP> [ssh port] [--new-key]}"
port="${2:-22}"
new_key="${3:-}"
repo="$(pwd)"
user=deploy
bin=/usr/local/bin/agent-to-earn-deploy
sudoers=/etc/sudoers.d/agent-to-earn-deploy

[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 1; }
[ -f "$repo/docker-compose.yml" ] && [ -f "$repo/scripts/vm_deploy.sh" ] || { echo "run from the repo root" >&2; exit 1; }

# Root-owned copy with the repo path baked in: the repo is writable by the containers (uid 1000).
sed "s|@REPO@|$repo|" "$repo/scripts/vm_deploy.sh" > "$bin.tmp"
chown root:root "$bin.tmp" && chmod 755 "$bin.tmp" && mv "$bin.tmp" "$bin"

id "$user" >/dev/null 2>&1 || useradd --create-home --shell /bin/sh "$user"
usermod -p '*' "$user"  # no password; "*" (unlike a "!" lock) still allows key login

printf '%s ALL=(root) NOPASSWD: %s\n' "$user" "$bin" > "$sudoers.tmp"
chmod 440 "$sudoers.tmp"
visudo -cf "$sudoers.tmp" >/dev/null && mv "$sudoers.tmp" "$sudoers"

home="$(getent passwd "$user" | cut -d: -f6)"
install -d -m 700 -o "$user" -g "$user" "$home/.ssh"
keys="$home/.ssh/authorized_keys"
if [ -s "$keys" ] && [ "$new_key" != "--new-key" ]; then
  echo "kept the existing deploy key (pass --new-key to rotate it); installed $bin"
  exit 0
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
ssh-keygen -q -t ed25519 -N "" -C "github-actions-deploy@agent-to-earn" -f "$tmp/key"
# restrict = no pty, no forwarding; the forced command ignores whatever the client asks to run
# and passes it to the deploy script, which only accepts a commit sha.
printf 'restrict,command="sudo -n %s \\"$SSH_ORIGINAL_COMMAND\\"" %s\n' "$bin" "$(cat "$tmp/key.pub")" > "$keys"
chown "$user:$user" "$keys" && chmod 600 "$keys"

target="$host"
[ "$port" = 22 ] || target="[$host]:$port"

cat <<EOF

Add these repository secrets (Settings > Secrets and variables > Actions):

VM_HOST
$host

VM_PORT
$port

VM_SSH_KEY  (copy everything, including the BEGIN and END lines)
$(cat "$tmp/key")

VM_KNOWN_HOSTS
$(for f in /etc/ssh/ssh_host_*_key.pub; do printf '%s %s\n' "$target" "$(cut -d' ' -f1-2 "$f")"; done)

The private key above is not stored on this VM. If you lose it, re-run with --new-key.
EOF
