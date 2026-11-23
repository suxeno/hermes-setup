import io
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'snapshot.py'


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = self.root / 'source'
        self.home.mkdir()
        self.key = self.root / 'key'
        self.output = self.root / 'snapshot.tar.gz.gpg'
        self.target = self.root / 'destination'

    def cli(self, *args, code=0):
        result = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result

    def fixture(self, name, content):
        path = self.home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def backup(self):
        self.cli('keygen', self.key)
        self.cli('backup', '--home', self.home, '--key-file', self.key, self.output)

    def restore(self, code=0):
        return self.cli('restore', '--home', self.target, '--key-file', self.key, self.output, code=code)

    def test_encrypted_round_trip(self):
        self.fixture('config.yaml', 'model: example\n')
        self.fixture('profiles/example/profile.yaml', 'name: example\n')
        script = self.fixture('scripts/test.sh', '#!/bin/sh\n')
        script.chmod(0o755)
        for name in ['.env', 'auth.json', 'sessions/chat', 'state.db', 'shared/nous_auth.json', 'skills/package/.git/config', 'skills/package/secret.env', 'skills/.hub/cache.json']:
            self.fixture(name, 'never include')
        (self.home / 'scripts/external').symlink_to(self.home / '.env')
        self.backup()
        self.assertEqual(self.key.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(b'model: example', self.output.read_bytes())
        self.restore()
        paths = {str(p.relative_to(self.target)) for p in self.target.rglob('*') if p.is_file()}
        self.assertEqual(paths, {'config.yaml', 'profiles/example/profile.yaml', 'scripts/test.sh'})
        self.assertEqual((self.target / 'config.yaml').read_text(), 'model: example\n')
        self.assertTrue(os.access(self.target / 'scripts/test.sh', os.X_OK))

    def test_restore_refuses_existing_home(self):
        self.fixture('config.yaml', 'new')
        self.backup()
        self.target.mkdir()
        (self.target / 'config.yaml').write_text('keep')
        self.restore(code=1)
        self.assertEqual((self.target / 'config.yaml').read_text(), 'keep')

    def test_corrupt_ciphertext_leaves_no_destination(self):
        self.fixture('config.yaml', 'original')
        self.backup()
        self.output.write_bytes(self.output.read_bytes()[:-10])
        self.restore(code=1)
        self.assertFalse(self.target.exists())

    def test_restore_rejects_unsafe_archive_paths_and_links(self):
        self.cli('keygen', self.key)
        for attack in ['../escaped', '/escaped', 'scripts/link', 'auth.json']:
            with self.subTest(attack=attack):
                plain = self.root / 'crafted.tar.gz'
                with tarfile.open(plain, 'w:gz') as tar:
                    config = tarfile.TarInfo('config.yaml')
                    config.size = 2
                    tar.addfile(config, io.BytesIO(b'{}'))
                    item = tarfile.TarInfo(attack)
                    if attack == 'scripts/link':
                        item.type = tarfile.SYMTYPE
                        item.linkname = '/tmp'
                    tar.addfile(item)
                self.output.unlink(missing_ok=True)
                subprocess.run(['gpg', '--batch', '--pinentry-mode', 'loopback', '--passphrase-file', self.key, '--output', self.output, '--symmetric', plain], check=True, capture_output=True)
                self.restore(code=1)
                self.assertFalse(self.target.exists())
                self.assertFalse((self.root / 'escaped').exists())
