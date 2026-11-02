import contextlib
import io
import subprocess
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from onec_route_check import check


class OneCRouteTests(unittest.TestCase):
    @patch('onec_route_check.subprocess.run')
    def test_compare_uses_no_credentials_and_emits_only_safe_shapes(self, run):
        def reply(cmd, **kwargs):
            if '/scripts/' in cmd[-1]:
                body = 'static loader'
            elif 'additionalAuthSettings' in cmd[-1]:
                body = '{"cred":"PRIVATE_CHALLENGE","helpURL":"PRIVATE_URL","sendMail":true}'
            else:
                body = 'var VERSION="8.3.24.1586";'
            Path(cmd[cmd.index('--output')+1]).write_text(body)
            return subprocess.CompletedProcess(cmd, 0, '200', '')
        run.side_effect = reply
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertTrue(check(interface='tun0'))
        self.assertNotIn('PRIVATE', output.getvalue())
        self.assertIn('sha256', output.getvalue())
        self.assertEqual(run.call_count, 3)
        for call in run.call_args_list:
            cmd = call.args[0]
            self.assertIn('--interface', cmd)
            self.assertNotIn('--user', cmd)
            self.assertNotIn('--location', cmd)
            self.assertNotIn('-k', cmd)
        self.assertIn('POST', run.call_args.args[0])
