from pathlib import Path
import signal
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from release_setup_agent import stop_agent, same_agent

AGENT = {'pid': 12, 'parent': 11, 'started': '123', 'exe': 'systemd-tty-ask-password-agent'}


class AgentReleaseTests(unittest.TestCase):
    def test_reused_pid_or_request_process_never_matches_agent(self):
        self.assertFalse(same_agent(AGENT, {**AGENT, 'started': '999'}))
        self.assertFalse(same_agent(AGENT, {**AGENT, 'exe': 'systemd-ask-password'}))

    def test_term_is_not_reported_as_exit_when_agent_ignores_it(self):
        alive = True
        def lookup(pid):
            return {'exe': 'systemctl'} if pid == 11 else (AGENT if alive else None)
        def send(pid, sig):
            nonlocal alive
            self.assertEqual(pid, 12)
            if sig == signal.SIGKILL:
                alive = False
        with patch('release_setup_agent.process', side_effect=lookup), patch('release_setup_agent.os.kill', side_effect=send) as kill, patch('release_setup_agent.time.sleep'):
            self.assertEqual(stop_agent(AGENT), 'exited_after_SIGKILL')
        self.assertEqual([c.args[1] for c in kill.call_args_list], [signal.SIGTERM, signal.SIGKILL])

    def test_parent_must_remain_systemctl(self):
        with patch('release_setup_agent.process', side_effect=lambda pid: AGENT if pid == 12 else {'exe': 'openvpn'}), patch('release_setup_agent.os.kill') as kill:
            self.assertEqual(stop_agent(AGENT), 'identity_changed_no_signal')
            kill.assert_not_called()
