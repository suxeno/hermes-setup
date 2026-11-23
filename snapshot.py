#!/usr/bin/env python3
"""Back up and restore the Hermes setup, not its live runtime state."""
import argparse
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile

FILES = {
    'config.yaml', 'profile.yaml', 'SOUL.md', 'ROLE.md', 'AGENTS.md',
    'KANBAN_WORKFLOW.md', 'MANAGER_ROUTING.md', 'SPECIALIST_CAPABILITIES.md',
    'SPECIALIST_WORKFLOW.md', 'TASK_ROUTING.md', 'discord-activity.json',
    'memories/MEMORY.md', 'memories/USER.md', 'cron/jobs.json',
    'tools/awwwards-mcp/package.json', 'tools/awwwards-mcp/package-lock.json',
}
ROOT_FILES = {'kanban/current', 'gsap-scrolltrigger-install-manifest.json',
              'skill-install-cloudflare-manifest.json'}
TREES = {'skills', 'plugins', 'scripts', 'hooks', 'skins', 'desktop-plugins', 'tui-widgets', 'pets'}
UNITS = {'hermes-gateway.service', 'hermes-dashboard.service', 'hermes-discord-activity.service'}
SKIP = {'__pycache__', 'node_modules', 'auth.json', 'credentials.json', 'nous_auth.json', 'vault', 'mcp-tokens'}
SUFFIXES = ('.lock', '.pyc', '.log', '.db', '.db-wal', '.db-shm', '.sqlite', '.sqlite3', '.env', '.pem', '.key')
PROFILE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]*\Z')
HOME = Path(os.environ.get('HERMES_HOME') or Path.home() / '.hermes')


def keep(part):
    return not (part.startswith('.') or part in SKIP or part.lower().endswith(SUFFIXES))


def allowed(name):
    parts = PurePosixPath(name).parts
    if not parts or name != '/'.join(parts) or any(p == '..' or not keep(p) for p in parts):
        return False
    if parts[:2] == ('migration', 'systemd'):
        return len(parts) == 3 and parts[2] in UNITS
    if name in ROOT_FILES:
        return True
    if parts[:2] == ('kanban', 'boards'):
        return len(parts) == 4 and parts[3] == 'board.json'
    if parts[0] == 'setup':
        return len(parts) >= 3 and parts[-1] == 'REPORT.md' and 'backups' not in parts
    if parts[0] == 'profiles':
        if len(parts) < 3 or not PROFILE.fullmatch(parts[1]):
            return False
        parts = parts[2:]
    return '/'.join(parts) in FILES or len(parts) > 1 and parts[0] in TREES


def as_regular(path):
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except FileNotFoundError:
        return False


def literal_file(root, name):
    path = root / name
    return as_regular(path) and path.resolve() == root.resolve() / name


def candidates(home, units):
    def collect(root, prefix=''):
        for name in sorted(FILES):
            path = root / name
            if literal_file(root, name):
                yield path, prefix + name
        for tree in sorted(TREES):
            directory = root / tree
            if directory.is_symlink() or not directory.is_dir():
                continue
            for base, dirs, files in os.walk(directory):
                dirs[:] = sorted(d for d in dirs if keep(d) and not (Path(base) / d).is_symlink())
                for name in sorted(files):
                    path = Path(base) / name
                    if keep(name) and as_regular(path):
                        yield path, prefix + path.relative_to(root).as_posix()

    yield from collect(home)
    root_names = ROOT_FILES | {
        p.relative_to(home).as_posix()
        for pattern in ('kanban/boards/*/board.json', 'setup/**/REPORT.md')
        for p in home.glob(pattern)
        if allowed(p.relative_to(home).as_posix())
    }
    for name in sorted(root_names):
        if literal_file(home, name):
            yield home / name, name
    profiles = home / 'profiles'
    if not profiles.is_symlink() and profiles.is_dir():
        for profile in sorted(profiles.iterdir()):
            if PROFILE.fullmatch(profile.name) and not profile.is_symlink() and profile.is_dir():
                yield from collect(profile, f'profiles/{profile.name}/')
    if units is not None:
        for name in sorted(UNITS):
            path = units / name
            if as_regular(path):
                yield path, f'migration/systemd/{name}'


def keygen(path):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as f:
        f.write(secrets.token_hex(32) + '\n')
    print(f'Key written to {path}; store it separately from the snapshot.')


def gpg(gnupg, key):
    if not as_regular(key) or key.stat().st_mode & 0o077:
        raise ValueError('Key must be a regular file with private permissions (chmod 600).')
    if not re.fullmatch(rb'[A-Fa-f0-9]{64}\n?', key.read_bytes()):
        raise ValueError('Use a key file created by keygen.')
    return ['gpg', '--no-options', '--homedir', str(gnupg), '--batch', '--quiet',
            '--no-symkey-cache', '--pinentry-mode', 'loopback', '--passphrase-file', str(key)]


def backup(home, units, key, archive, gnupg):
    if not as_regular(home / 'config.yaml'):
        raise ValueError('Source is missing a regular config.yaml.')
    if os.path.lexists(archive):
        raise FileExistsError(f'Archive already exists: {archive}')
    count = 0
    with tempfile.NamedTemporaryFile(dir=archive.parent) as encrypted:
        command = gpg(gnupg, key) + ['--cipher-algo', 'AES256', '--compress-algo', 'none',
                                     '--s2k-count', '65011712', '--symmetric']
        with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=encrypted) as proc:
            pipe = proc.stdin
            assert pipe is not None
            try:
                with tarfile.open(fileobj=pipe, mode='w|gz') as tar:
                    for source, name in candidates(home, units):
                        if not allowed(name):
                            raise ValueError(f'Unexpected snapshot path: {name}')
                        with os.fdopen(os.open(source, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as f:
                            st = os.fstat(f.fileno())
                            if not stat.S_ISREG(st.st_mode):
                                raise ValueError(f'Source is not a regular file: {name}')
                            member = tarfile.TarInfo(name)
                            member.size = st.st_size
                            member.mode = 0o700 if st.st_mode & 0o100 else 0o600
                            tar.addfile(member, f)
                            count += 1
            finally:
                pipe.close()
            if proc.wait() != 0:
                raise ValueError('GnuPG encryption failed.')
        os.link(encrypted.name, archive)
    print(f'Backed up {count} files to {archive}.')


def unpack(plain, stage):
    seen = set()
    with tarfile.open(fileobj=plain, mode='r|gz') as tar:
        for member in tar:
            name = member.name
            if not allowed(name) or not member.isfile() or name in seen:
                raise ValueError(f'Unexpected snapshot entry: {name!r}')
            seen.add(name)
            dest = stage / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            src = tar.extractfile(member)
            if src is None:
                raise ValueError(f'Entry has no file data: {name!r}')
            with src, dest.open('xb') as out:
                shutil.copyfileobj(src, out)
            dest.chmod(0o700 if member.mode & 0o100 else 0o600)
    if 'config.yaml' not in seen:
        raise ValueError('Archive is missing config.yaml.')
    return len(seen)


def restore(home, key, archive, gnupg):
    if os.path.lexists(home):
        raise FileExistsError(f'Restore requires a new home; already exists: {home}')
    with tempfile.TemporaryFile(dir=gnupg) as plain:
        subprocess.run(gpg(gnupg, key) + ['--decrypt', '--', str(archive)], stdout=plain, check=True)
        plain.seek(0)
        # Reserve the final path without replacing an existing file, dir, or symlink.
        home.mkdir(mode=0o700)
        try:
            count = unpack(plain, home)
        except BaseException:
            shutil.rmtree(home)
            raise
    print(f'Restored {count} files to {home}. No services started.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest='action', required=True)
    actions.add_parser('keygen').add_argument('key', type=Path)
    for action in ('backup', 'restore'):
        p = actions.add_parser(action)
        p.add_argument('archive', type=Path)
        p.add_argument('--home', type=Path, default=HOME)
        p.add_argument('--key-file', type=Path, required=True)
        if action == 'backup':
            p.add_argument('--units-dir', type=Path, help='Include named systemd user units as reference copies')
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.action == 'keygen':
            keygen(args.key)
        else:
            with tempfile.TemporaryDirectory(prefix='hermes-gpg-') as gnupg:
                if args.action == 'backup':
                    backup(args.home, args.units_dir, args.key_file, args.archive, gnupg)
                else:
                    restore(args.home, args.key_file, args.archive, gnupg)
    except (OSError, ValueError, tarfile.TarError, subprocess.CalledProcessError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
