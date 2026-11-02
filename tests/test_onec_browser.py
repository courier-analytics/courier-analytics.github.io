import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from onec_browser import save_credentials, load_credentials, final_login_shape


class OneCBrowserTests(unittest.TestCase):
    @patch('onec_browser.getpass.getpass', side_effect=['1C user', 'private password'])
    def test_hidden_credentials_saved_owner_only_and_never_replaced(self, prompt):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'credentials.json'
            save_credentials(path)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(load_credentials(path)['password'], 'private password')
            save_credentials(path)
            self.assertEqual(prompt.call_count, 2)
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                load_credentials(path)

    def test_symlink_credentials_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'real'
            path.write_text('{}')
            link = Path(directory)/'link'
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                load_credentials(link)

    def test_http_200_challenge_is_not_successful_authentication(self):
        self.assertFalse(final_login_shape({'cred': 'challenge'}))
        self.assertFalse(final_login_shape({'error': 'denied'}))
        self.assertTrue(final_login_shape({'passwordExpirationStatus': 0, 'fullLocale': 'ru_RU'}))
        self.assertTrue(final_login_shape({'response': {'passwordExpirationStatus': 0}}))
