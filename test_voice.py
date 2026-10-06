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
    def test_attention_filter(self):
        event = {'hook_event_name': 'Notification', 'notification_type': 'permission_prompt',
                 'session_id': '123456789', 'cwd': '/project/website', 'message': 'Please approve.'}
        self.assertIn('Mac one. Project website.', voice.render(event, 'Mac one'))
        self.assertIn('Session 12345678.', voice.render(event, 'Mac one'))
        for kind in ['idle_prompt', 'auth_success', 'agent_completed']:
            self.assertIsNone(voice.render(dict(event, notification_type=kind), 'Mac one'))
        self.assertIn('rate limit', voice.render(dict(event, hook_event_name='StopFailure', error='rate_limit'), 'Mac one'))

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
            self.assertEqual(installed['hooks']['Stop'], original['hooks']['Stop'])
            self.assertEqual(len(installed['hooks']['Notification']), 2)
            self.assertEqual(len(installed['hooks']['StopFailure']), 1)
            self.assertEqual(len(list(Path(folder).glob('settings.json.voice-backup-*'))), 2)


if __name__ == '__main__':
    unittest.main()
