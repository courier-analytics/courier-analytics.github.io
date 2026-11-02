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
