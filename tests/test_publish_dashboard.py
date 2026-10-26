import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from publish_dashboard import publish


class PublisherTests(unittest.TestCase):
    def git(self, *args, cwd=None):
        return subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                               *args], cwd=cwd, check=True, capture_output=True, text=True).stdout

    def test_only_json_published_and_manual_site_changes_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            remote = root/'remote.git'
            self.git('init', '--bare', str(remote))
            seed = root/'seed'
            self.git('clone', str(remote), str(seed))
            self.git('checkout', '-b', 'main', cwd=seed)
            (seed/'index.html').write_text('manual site data')
            self.git('add', 'index.html', cwd=seed)
            self.git('commit', '-m', 'Initial site', cwd=seed)
            self.git('push', 'origin', 'main', cwd=seed)
            feed = root/'feed.json'
            feed.write_text(json.dumps({'schema_version': 1, 'records': [{
                'date': '2026-10-26', 'shop_id': 5818, 'booked_places': 56,
                'capacity': 86, 'fill_percent': 65.12, 'source': 'slots_export',
                'reported_at': '2026-10-26T07:34:18+00:00', 'token': 'must not publish'}]}))
            self.assertIn('pushed', publish(feed, root/'publisher', str(remote)))
            self.git('fetch', 'origin', cwd=seed)
            self.assertEqual(self.git('show', 'origin/main:index.html', cwd=seed).strip(), 'manual site data')
            public = self.git('show', 'origin/main:data/dashboard.json', cwd=seed)
            self.assertNotIn('must not publish', public)
            self.assertEqual(self.git('diff-tree', '--no-commit-id', '--name-only', '-r', 'origin/main', cwd=seed).strip(), 'data/dashboard.json')
            self.assertIn('already up to date', publish(feed, root/'publisher', str(remote)))
            (root/'publisher/index.html').write_text('local user change')
            with self.assertRaises(ValueError):
                publish(feed, root/'publisher', str(remote))
            self.assertEqual((root/'publisher/index.html').read_text(), 'local user change')
