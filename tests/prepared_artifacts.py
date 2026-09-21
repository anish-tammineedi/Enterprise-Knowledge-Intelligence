"""Test-only availability guard; production integrity verification stays strict."""
import hashlib
import json
from pathlib import Path
import subprocess
import unittest

from src.generation.retrieval import verify_protected


SKIP_REASON = 'prepared local corpus/artifacts unavailable in clean checkout'
LOCAL_ROOTS = ('data/raw/sec_filings/', 'data/processed/')


def require_prepared_artifacts(root, manifest=None, historical=None):
    root = Path(root)
    if manifest is None:
        manifest = json.loads((root / 'configs/generation_protected.json').read_text())
    expected = dict(manifest['sha256'])
    for path, digest in (historical or {}).items():
        source = root / path
        # The historical audit predates the documented dataset newline cleanup.
        if path == 'configs/dataset.json' and source.is_file():
            current = source.read_bytes()
            if hashlib.sha256(current + b'\n').hexdigest() == digest:
                digest = hashlib.sha256(current).hexdigest()
        if path in expected and expected[path] != digest:
            raise ValueError('Conflicting protected artifact hashes: ' + path)
        expected[path] = digest

    missing = []
    for path, digest in expected.items():
        source = root / path
        if not source.exists():
            missing.append(path)
        elif not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise ValueError('Protected artifact content changed: ' + path)

    # Keep exact inventory checking (including unexpected files) even before a skip.
    present = {p: h for p, h in manifest['sha256'].items() if p not in missing}
    verify_protected(root, {**manifest, 'sha256': present})
    if missing:
        # Git excludes tracked paths from check-ignore, even if an ignore rule matches.
        result = subprocess.run(['git', 'check-ignore', '--stdin'], cwd=root,
                                input='\n'.join(missing) + '\n', text=True,
                                capture_output=True)
        if result.returncode not in (0, 1):
            raise RuntimeError('Cannot establish ignored artifact availability: ' + result.stderr)
        ignored = set(result.stdout.splitlines())
        if any(p not in ignored or not p.startswith(LOCAL_ROOTS) for p in missing):
            raise ValueError('Protected artifact inventory changed: ' + ', '.join(missing))
        raise unittest.SkipTest(SKIP_REASON)
    verify_protected(root, manifest)
