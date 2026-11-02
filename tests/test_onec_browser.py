import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from onec_browser import save_credentials, load_credentials, final_login_shape, failure_shape, sync_verified_credentials


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

    @patch('onec_browser.getpass.getpass', side_effect=['correct user', 'correct password'])
    def test_explicit_replacement_is_atomic_and_private(self, prompt):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'credentials.json'
            path.write_text('{"username":"old","password":"old"}')
            save_credentials(path, replace=True)
            self.assertEqual(load_credentials(path)['username'], 'correct user')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_symlink_credentials_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'real'
            path.write_text('{}')
            link = Path(directory)/'link'
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                load_credentials(link)

    def test_failure_diagnostics_do_not_expose_server_messages_or_accounts(self):
        import base64
        description = 'Неправильное имя пользователя или пароль: PRIVATE_ACCOUNT'
        text = json.dumps({'exception': {'reason': 402, 'inner': {
            'reason': -15, 'encoded': True, 'descr': base64.b64encode(description.encode()).decode()}}})
        shape = failure_shape(text)
        self.assertEqual(shape['reason_codes'], [-15, 402])
        self.assertIn('credentials_rejected', shape['categories'])
        self.assertNotIn('PRIVATE_ACCOUNT', json.dumps(shape))
        self.assertIn('license_unavailable', failure_shape('Не найдена лицензия PRIVATE_SERVER')['categories'])

    @patch('onec_browser.subprocess.run')
    def test_only_confirmed_manual_credentials_are_sent_to_vps_stdin(self, run):
        import subprocess
        saved = [{'username': 'manual-user', 'password': 'manual-secret'}]
        self.assertFalse(sync_verified_credentials(saved, False))
        run.assert_not_called()
        run.return_value = subprocess.CompletedProcess([], 0)
        self.assertTrue(sync_verified_credentials(saved, True))
        self.assertEqual(saved, [])
        args = run.call_args.args[0]
        self.assertNotIn('manual-secret', str(args))
        self.assertNotIn('manual-user', str(args))
        self.assertEqual(json.loads(run.call_args.kwargs['input'])['password'], 'manual-secret')
        with self.assertRaises(ValueError):
            sync_verified_credentials([], True)

    def test_http_200_challenge_is_not_successful_authentication(self):
        self.assertFalse(final_login_shape({'cred': 'challenge'}))
        self.assertFalse(final_login_shape({'error': 'denied'}))
        self.assertTrue(final_login_shape({'passwordExpirationStatus': 0, 'fullLocale': 'ru_RU'}))
        self.assertTrue(final_login_shape({'response': {'passwordExpirationStatus': 0}}))
