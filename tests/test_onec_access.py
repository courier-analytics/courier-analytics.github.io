import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from onec_access import inspect_page


class OneCEntryTests(unittest.TestCase):
    def test_static_resource_paths_do_not_allow_api_calls_or_other_hosts(self):
        from onec_access import asset_path
        self.assertEqual(asset_path('scripts/mod_auth.js?sysver=8.3.24'),
                         '/couriers/ru_RU/scripts/mod_auth.js?sysver=8.3.24')
        for path in ('https://other.invalid/authform.html', '../authform.html',
                     'e1cib/login', 'scripts/a.js?password=hidden', '//other.invalid/x.js'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                asset_path(path)

    @patch('onec_access.subprocess.run')
    def test_static_bundle_contains_only_forms_scripts_and_no_response_headers(self, run):
        from onec_access import collect_assets
        import zipfile, contextlib, io
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            folder = Path(directory)
            private = folder/'private'
            private.mkdir()
            def respond(command, **kwargs):
                content = ('<script src="scripts/mod_auth.js?sysver=8.3"></script>'
                           if '.html?' in command[-1] else '/* static */')
                Path(command[command.index('--output')+1]).write_text(content)
                return subprocess.CompletedProcess(command, 0, '200', '')
            run.side_effect = respond
            collect_assets('10.210.254.19', 'tun0', folder, private, 'var VERSION="8.3";')
            archive = private/'onec-login-assets.zip'
            self.assertEqual(archive.stat().st_mode & 0o777, 0o600)
            with zipfile.ZipFile(archive) as bundle:
                self.assertEqual(set(bundle.namelist()), {'entry.html', 'mainform.html',
                    'authform.html', 'scripts/mod_auth.js', 'manifest.json'})
            self.assertEqual(run.call_count, 3)

    @patch('onec_access.corporate_interface', return_value='tun0')
    @patch('onec_access.subprocess.run')
    def test_only_fixed_https_entry_point_is_read_and_private_values_not_printed(self, run, interface):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def respond(command, **kwargs):
                Path(command[command.index('--dump-header')+1]).write_text(
                    'HTTP/1.1 200 OK\nSet-Cookie: SECRET_SESSION\n')
                Path(command[command.index('--output')+1]).write_text(
                    '<form><input type="password" value="SECRET_PASSWORD"></form>'
                    '<script src="/app.js?token=SECRET_TOKEN"></script>1C:Enterprise')
                return subprocess.CompletedProcess(command, 0, '200', '')
            run.side_effect = respond
            import contextlib, io
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertTrue(inspect_page('10.210.254.19', root, root/'private'))
            self.assertNotIn('SECRET', output.getvalue())
            command = run.call_args.args[0]
            self.assertIn('--interface', command)
            self.assertIn('couriers.int.vkusvill.ru:443:10.210.254.19', command)
            self.assertNotIn('-k', command)
            self.assertNotIn('--location', command)
            self.assertNotIn('--user', command)
            self.assertEqual((root/'private/onec-login-page.html').stat().st_mode & 0o777, 0o600)

    @patch('onec_access.corporate_interface', return_value='tun0')
    @patch('onec_access.subprocess.run', return_value=subprocess.CompletedProcess([], 60, '000', 'SECRET_ERROR'))
    def test_untrusted_certificate_is_not_bypassed(self, run, interface):
        import contextlib, io
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()) as output:
            root = Path(directory)
            self.assertFalse(inspect_page('10.210.254.19', root, root/'private'))
            self.assertNotIn('SECRET', output.getvalue())
            self.assertFalse((root/'private/onec-login-page.html').exists())
