# Hermes setup backup

Encrypted checkpoint of the Hermes manager and specialist profiles. This is a setup backup, not a backup of conversations, workspaces, or running tasks.

## Back up or sync

Requires Bash, Python 3.10+, and GnuPG 2.2+. GitHub sync also requires Git and an authenticated `gh` CLI.

```bash
cd hermes-setup
bash sync.sh             # Create a new local checkpoint after any setup change
bash sync.sh --publish   # Refresh GitHub's checkpoint; private repo only
```

Local archives are saved under `~/.local/share/hermes-setup/`. The first local run creates `setup.key` there. Store a copy of this key separately in a password manager or another secure location. Do not put it in Git or send it in chat. Losing the key makes the backups unreadable.

`--publish` requires a clean `main` that matches GitHub and verifies that the repo is private. It commits only `backup/setup.tar.gz.gpg`. Each update leaves the previous encrypted archive in Git history. Keep the repo private even though the archives are encrypted. Local sync does not commit or push.

## Restore on another device

1. Install [Hermes Agent](https://hermes-agent.nousresearch.com/docs/) on the target device, preferably a release at least as recent as the source. Clone this repo. If `backup/setup.tar.gz.gpg` is absent, transfer an encrypted local checkpoint from the source device. Retrieve `setup.key` separately.
2. Restore to a path that does **not** exist. The script will not overwrite an installed Hermes home or start services.

   ```bash
   git clone https://github.com/suxeno/hermes-setup.git
   cd hermes-setup
   chmod 600 "$HOME/setup.key"
   python3 snapshot.py restore --home "$HOME/.hermes-restored" \
     --key-file "$HOME/setup.key" backup/setup.tar.gz.gpg
   export HERMES_HOME="$HOME/.hermes-restored"
   hermes profile list
   hermes config check
   ```

3. Reconnect model providers and MCP accounts, and restore API keys and bot credentials from your secret store into the appropriate profile environments. Check absolute paths, local tool executables, project directories, and integration endpoints before starting anything. For the optional Awwwards MCP installation, run `npm ci --prefix "$HERMES_HOME/profiles/creative/tools/awwwards-mcp"` if the restored config uses it.
4. On Linux, review the reference units in `$HERMES_HOME/migration/systemd/`. Adjust paths, reinstall the gateway with `hermes gateway install` if needed, and enable only the services you want. Stop the old gateway before starting a replacement with the same bot credentials. Reconfigure remote dashboard access separately.

## Backup contents

- Main and specialist configs, profile metadata, identity/role prompts, and orchestration policies.
- Skills, plugins, helper scripts, hooks, and appearance assets where present. Includes persistent Markdown memory.
- Kanban board metadata, Discord activity relay settings, schedule definitions if present, selected installation notes and package manifests, and reference systemd units.
- Excludes standard credential stores (`.env`, OAuth, vault), session history, task databases, caches, project workspaces, binaries and symlinks. Config or scripts can still contain inline secrets, which is why the whole snapshot is encrypted.

Run `python3 -m unittest discover -s tests -v` to check the backup and restore tools.
