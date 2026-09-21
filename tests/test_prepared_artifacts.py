import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from prepared_artifacts import require_prepared_artifacts, SKIP_REASON
from src.generation.retrieval import verify_protected


class PreparedArtifactTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.git('init', '-q')
        (self.root / '.gitignore').write_text('data/processed/\n')
        self.tracked = self.root / 'frozen/result.json'
        self.local = self.root / 'data/processed/corpus.json'
        for path in (self.tracked, self.local):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('original')
        self.git('add', '.gitignore', 'frozen/result.json')
        self.manifest = {'roots': ['frozen', 'data/processed'], 'sha256': {
            str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (self.tracked, self.local)}}

    def git(self, *args):
        subprocess.run(['git', *args], cwd=self.root, check=True, capture_output=True)

    def check(self):
        require_prepared_artifacts(self.root, self.manifest)

    def test_missing_ignored_corpus_skips(self):
        self.local.unlink()
        with self.assertRaisesRegex(unittest.SkipTest, SKIP_REASON):
            self.check()
        with self.assertRaisesRegex(ValueError, 'inventory changed'):
            verify_protected(self.root, self.manifest)

    def test_complete_prepared_set_runs_full_verification(self):
        with patch('prepared_artifacts.verify_protected', wraps=verify_protected) as verify:
            self.check()
        verify.assert_called_with(self.root, self.manifest)

    def test_wrong_tracked_content_fails_even_without_corpus(self):
        for missing in (False, True):
            with self.subTest(missing=missing):
                if missing:
                    self.local.unlink()
                self.tracked.write_text('tampered')
                with self.assertRaisesRegex(ValueError, 'content changed'):
                    self.check()

    def test_missing_tracked_file_fails_even_without_corpus(self):
        self.local.unlink()
        self.tracked.unlink()
        with self.assertRaisesRegex(ValueError, 'inventory changed'):
            self.check()

    def test_tracked_file_matching_ignore_rule_cannot_skip(self):
        self.git('add', '-f', 'data/processed/corpus.json')
        self.local.unlink()
        with self.assertRaisesRegex(ValueError, 'inventory changed'):
            self.check()

    def test_present_ignored_corruption_fails(self):
        self.local.write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'content changed'):
            self.check()

    def test_unexpected_inventory_fails_before_skip(self):
        self.local.unlink()
        (self.tracked.parent / 'extra').write_text('unexpected')
        with self.assertRaisesRegex(ValueError, 'inventory changed'):
            self.check()

    def test_unignored_missing_corpus_fails(self):
        (self.root / '.gitignore').write_text('')
        self.local.unlink()
        with self.assertRaisesRegex(ValueError, 'inventory changed'):
            self.check()

    def test_historical_corruption_fails_before_skip(self):
        historical = self.root / 'history.json'
        historical.write_text('tampered')
        self.git('add', 'history.json')
        self.local.unlink()
        with self.assertRaisesRegex(ValueError, 'content changed'):
            require_prepared_artifacts(self.root, self.manifest,
                                       {'history.json': hashlib.sha256(b'original').hexdigest()})
