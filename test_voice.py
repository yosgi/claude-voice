import json
from pathlib import Path
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import voice


class VoiceTests(unittest.TestCase):
    def test_all_notifications_are_spoken(self):
        event = {'hook_event_name': 'Notification', 'notification_type': 'permission_prompt',
                 'session_id': '123456789', 'cwd': '/project/website', 'message': 'Please approve.'}
        self.assertIn('Mac one. Project website.', voice.render(event, 'Mac one'))
        self.assertIn('Session 12345678.', voice.render(event, 'Mac one'))
        for kind in ['idle_prompt', 'auth_success', 'agent_completed']:
            self.assertIsNotNone(voice.render(dict(event, notification_type=kind), 'Mac one'))
        self.assertIn('Claude notification.', voice.render(dict(event, notification_type='future_event'), 'Mac one'))
        self.assertIn('rate limit', voice.render(dict(event, hook_event_name='StopFailure', error='rate_limit'), 'Mac one'))

    def test_lifecycle_events(self):
        for kind, phrase in [('Stop', 'finished responding'), ('TaskCompleted', 'task completed'),
                             ('SubagentStop', 'subagent finished'), ('PostToolUseFailure', 'tool failed'),
                             ('PermissionRequest', 'needs permission'), ('PermissionDenied', 'permission was denied'),
                             ('Elicitation', 'waiting for your input'), ('SessionStart', 'session started'),
                             ('SessionEnd', 'session ended')]:
            with self.subTest(kind=kind):
                self.assertIn(phrase, voice.render({'hook_event_name': kind}, 'Mac one'))
        self.assertIsNone(voice.render({'hook_event_name': 'PreToolUse'}, 'Mac one'))

    def test_manual_test_waits_for_speech(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(sys, 'argv', ['voice.py', 'test', '--state', folder]), \
                 patch.object(voice.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as say, \
                 patch.object(voice.subprocess, 'Popen') as detached:
                voice.main()
            say.assert_called_once()
            detached.assert_not_called()
            with voice.database(Path(folder)) as db:
                self.assertEqual(db.execute('SELECT status FROM alerts').fetchone()[0], 'spoken')

    def test_concurrent_dedup_and_ordered_speech(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder)
            voice.database(state).close()
            with ThreadPoolExecutor(max_workers=8) as pool:
                accepted = list(pool.map(lambda _: voice.enqueue(state, 'same alert', 'same-key'), range(24)))
            self.assertEqual(sum(accepted), 1)
            for i in range(5):
                self.assertTrue(voice.enqueue(state, f'alert {i}', str(i)))
            spoken = []
            with patch.object(voice.subprocess, 'run', side_effect=lambda command, **kw:
                              (spoken.append(command[-1]) or SimpleNamespace(returncode=0))):
                voice.work(state)
            self.assertEqual(spoken, ['same alert'] + [f'alert {i}' for i in range(5)])
            with voice.database(state) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM alerts WHERE status='spoken'").fetchone()[0], 6)

    def test_install_preserves_settings_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = Path(folder) / 'settings.json'
            original = {'env': {'EXAMPLE': 'preserved'}, 'hooks': {
                'Notification': [{'hooks': [{'type': 'command', 'command': 'existing-notification'}]}],
                'Stop': [{'hooks': [{'type': 'command', 'command': 'existing-stop'}]}]}}
            settings.write_text(json.dumps(original))
            for _ in range(2):
                subprocess.run([sys.executable, str(Path(__file__).with_name('install.py')),
                                '--computer', 'Mac one', '--settings', str(settings),
                                '--destination', str(Path(folder) / 'installed')], check=True, capture_output=True)
            installed = json.loads(settings.read_text())
            self.assertEqual(installed['env'], original['env'])
            self.assertEqual(installed['hooks']['Stop'][0], original['hooks']['Stop'][0])
            self.assertEqual(len(installed['hooks']['Stop']), 2)
            self.assertEqual(len(installed['hooks']['Notification']), 2)
            self.assertNotIn('matcher', installed['hooks']['Notification'][-1])
            self.assertEqual(len(installed['hooks']['StopFailure']), 1)
            for kind in ['TaskCompleted', 'SubagentStop', 'PostToolUseFailure', 'PermissionRequest',
                         'PermissionDenied', 'Elicitation', 'SessionStart', 'SessionEnd']:
                self.assertEqual(len(installed['hooks'][kind]), 1)
            self.assertEqual(len(list(Path(folder).glob('settings.json.voice-backup-*'))), 2)


if __name__ == '__main__':
    unittest.main()
