# Hermes setup backup

Restore the manager and its specialist profiles on a fresh Hermes install, or sync changes from your current device to GitHub. The repo holds the scripts; the setup itself is an encrypted archive.

## Prerequisites

The scripts use Bash, Git, Python 3.10+, and GnuPG 2.2+. The commands below also install the GitHub CLI (`gh`) for private repo access and publishing.

**Debian / Ubuntu / Raspberry Pi OS / WSL:**

```bash
sudo apt update
sudo apt install bash ca-certificates curl git python3 gnupg gh
```

**macOS** (with [Homebrew](https://brew.sh/)):

```bash
brew install git python gnupg gh
```

**Fresh device only:** install Hermes without running the setup wizard. If Hermes is already installed, skip this command.

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash -s -- --skip-setup
```

Open a new terminal if `hermes --version` is not found. For a private clone or to publish, sign in once with `gh auth login --hostname github.com --git-protocol https --web`, then run `gh auth setup-git`. Skip login if `gh auth status` already shows the right account.

## Use this setup on a new device

1. **Clone and get the two restore files.** Clone the repo, then put the original `setup.key` at `$HOME/setup.key` using your secure copy. Do not generate a new key. If the clone contains `backup/setup.tar.gz.gpg`, use it. Otherwise copy the latest `setup-*.tar.gz.gpg` from `~/.local/share/hermes-setup/` on the source device to `$HOME/setup.tar.gz.gpg` on the new device. Transfer the key separately; never commit it or send it in chat.

   ```bash
   git clone https://github.com/suxeno/hermes-setup.git
   cd hermes-setup
   ```

2. **Restore and select the restored home.** The destination must not exist. This leaves the vanilla `~/.hermes` untouched and starts no services.

   ```bash
   archive=backup/setup.tar.gz.gpg
   [ -f "$archive" ] || archive="$HOME/setup.tar.gz.gpg"
   chmod 600 "$HOME/setup.key"
   python3 snapshot.py restore --home "$HOME/.hermes-restored" \
     --key-file "$HOME/setup.key" "$archive"

   export HERMES_HOME="$HOME/.hermes-restored"
   hermes config path
   hermes profile list
   ```

3. **Reconnect and run.** `hermes config get model.provider` shows the saved provider ID. For OAuth, run `hermes auth add PROVIDER` with that ID. For API keys, use the `.env` location shown by `hermes config env-path`. Add `-p coder` after `hermes` to run either command for that profile. Then launch the manager with `hermes` or a specialist with `hermes -p coder`. Repeat the `HERMES_HOME` export in new terminals, or add it to your shell startup file to make this setup the default.

   Before enabling optional integrations, fix paths that still point to the source machine and reconnect MCP accounts and bots. If you use Awwwards MCP, install Node.js/npm and run `npm ci --prefix "$HERMES_HOME/profiles/creative/tools/awwwards-mcp"`. Review the Linux service templates in `$HERMES_HOME/migration/systemd/` before enabling them. Don't run two gateways with the same bot credentials.

## Sync setup changes to GitHub

Run this on the device whose configuration you want to back up. If you use a custom Hermes home, make sure `HERMES_HOME` points to the manager home, not a specialist profile.

```bash
cd /path/to/hermes-setup
bash sync.sh                          # Local checkpoint only
```

Local snapshots go to `~/.local/share/hermes-setup/`. The first local sync creates `setup.key` there. Keep an independent copy; without it, your backups cannot be restored. If publishing from a restored device, pass the original key with `HERMES_BACKUP_KEY_FILE="$HOME/setup.key" bash sync.sh --publish` instead of creating a new one.

To sync to GitHub, first make `suxeno/hermes-setup` **private**. In a clean `main` checkout with GitHub CLI authenticated, run:

```bash
git pull --ff-only
bash sync.sh --publish
```

This makes a fresh encrypted snapshot, commits only `backup/setup.tar.gz.gpg`, and pushes it. Previous encrypted snapshots remain in Git history. Publishing to a public repo is blocked.

## Backup contents

| Category | Details |
| --- | --- |
| Manager and profiles | Settings, profile metadata, identity and role prompts, routing and orchestration policies |
| Customizations | Skills, plugins, scripts, hooks, appearance assets where present, and persistent Markdown memory |
| Automation | Kanban board metadata, Discord activity relay settings, and cron definitions if present |
| Migration references | Selected setup notes, package manifests, and Linux systemd unit templates |
| Not included | Standard credential stores (`.env`, OAuth, vault), chat history, task databases, caches, project workspaces, installed binaries, or symlinks |

Tests: `python3 -m unittest discover -s tests -v`.
