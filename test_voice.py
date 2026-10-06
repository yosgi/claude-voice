import json
import io
import time
from pathlib import Path
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

import voice


class VoiceTests(unittest.TestCase):
    def test_only_key_notifications_are_spoken(self):
        event = {'hook_event_name': 'Notification', 'notification_type': 'permission_prompt',
                 'session_id': '123456789', 'cwd': '/project/website', 'message': 'secret details' * 100}
        message = voice.render(event, 'Mac one')
        self.assertEqual(message, 'Mac one. Project website. Claude needs permission.')
        for kind in ['idle_prompt', 'auth_success', 'future_event', 'quota_auto_resume_fired']:
            self.assertIsNone(voice.render(dict(event, notification_type=kind), 'Mac one'))
        self.assertIn('needs your input', voice.render(dict(event, notification_type='agent_needs_input'), 'Mac one'))
        self.assertIn('task ended', voice.render(dict(event, notification_type='agent_completed'), 'Mac one'))
        error = voice.render(dict(event, hook_event_name='StopFailure', error='rate_limit', error_details='private traceback' * 100), 'Mac one')
        self.assertIn('rate limit', error)
        self.assertNotIn('private', error)

    def test_completion_is_short_and_routine_events_are_silent(self):
        for kind, phrase in [('Stop', 'finished responding'), ('TaskCompleted', 'task completed')]:
            message = voice.render({'hook_event_name': kind, 'last_assistant_message': 'long result' * 100}, 'Mac one')
            self.assertIn(phrase, message)
            self.assertLess(len(message), 150)
            self.assertNotIn('long result', message)
        for kind in ['SubagentStop', 'PostToolUseFailure', 'PermissionRequest', 'PermissionDenied',
                     'Elicitation', 'SessionStart', 'SessionEnd', 'PreToolUse']:
            self.assertIsNone(voice.render({'hook_event_name': kind}, 'Mac one'))
        self.assertIsNone(voice.render({'hook_event_name': 'Stop', 'stop_hook_active': True}, 'Mac one'))

    def test_event_storm_is_coalesced_without_extra_workers(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder)
            event = {'hook_event_name': 'Notification', 'notification_type': 'permission_prompt',
                     'cwd': '/project/website', 'session_id': 'one'}
            with patch.object(voice.subprocess, 'Popen') as worker:
                for i in range(50):
                    payload = dict(event, message=f'Changing command {i}')
                    with patch.object(sys, 'argv', ['voice.py', 'hook', '--state', folder, '--computer', 'Mac one']), \
                         patch.object(sys, 'stdin', io.StringIO(json.dumps(payload))):
                        voice.main()
                worker.assert_called_once()
            with voice.database(state) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM alerts').fetchone()[0], 1)
                self.assertEqual(db.execute('SELECT repeats FROM merged_alerts').fetchone()[0], 49)
            first = dict(event, hook_event_name='Stop')
            second = dict(event, hook_event_name='TaskCompleted')
            self.assertEqual(voice.alert_key(first, 'Mac one'), voice.alert_key(second, 'Mac one'))
            self.assertNotEqual(voice.alert_key(event, 'Mac one'), voice.alert_key(dict(event, session_id='two'), 'Mac one'))

    def test_backlog_is_bounded_and_stale_alerts_expire(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder)
            for i in range(50):
                voice.enqueue(state, f'alert {i}', str(i))
            with voice.database(state) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM alerts WHERE status='pending'").fetchone()[0], 20)
                db.execute('UPDATE alerts SET created=?', (time.time()-301,))
            with patch.object(voice, 'speak') as say:
                voice.work(state)
                say.assert_not_called()

    def test_manual_test_waits_for_speech(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(sys, 'argv', ['voice.py', 'test', '--state', folder]), \
                 patch.object(voice, 'speak', return_value='spoken') as say, \
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
            with patch.object(voice, 'speak', side_effect=lambda state, message, generation:
                              (spoken.append(message) or 'spoken')):
                voice.work(state)
            self.assertEqual(spoken, ['same alert'] + [f'alert {i}' for i in range(5)])
            with voice.database(state) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM alerts WHERE status='spoken'").fetchone()[0], 6)

    def test_mute_stop_and_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder)
            voice.enqueue(state, 'queued', 'first')
            generation = voice.cancellation(state)
            voice.control(state, 'mute')
            self.assertNotEqual(voice.cancellation(state), generation)
            self.assertFalse(voice.enqueue(state, 'new', 'second'))
            with voice.database(state) as db:
                self.assertEqual(db.execute('SELECT status FROM alerts').fetchone()[0], 'cancelled')
            voice.control(state, 'unmute')
            self.assertTrue(voice.enqueue(state, 'new', 'second'))
            voice.control(state, 'stop')
            self.assertFalse((state / 'muted').exists())
            self.assertTrue(voice.enqueue(state, 'future', 'third'))

    def test_stop_terminates_only_owned_speech(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder)
            generation = voice.cancellation(state)
            speech = unittest.mock.MagicMock()
            speech.__enter__.return_value = speech
            def poll():
                voice.control(state, 'stop')
                return None
            speech.poll.side_effect = poll
            with patch.object(voice.subprocess, 'Popen', return_value=speech):
                self.assertEqual(voice.speak(state, 'message', generation), 'cancelled')
            speech.terminate.assert_called_once()
            speech.wait.assert_called_once()

    def test_install_preserves_settings_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = Path(folder) / 'settings.json'
            original = {'env': {'EXAMPLE': 'preserved'}, 'hooks': {
                'Notification': [{'hooks': [{'type': 'command', 'command': 'existing-notification'}]}],
                'Stop': [{'hooks': [{'type': 'command', 'command': 'existing-stop'}]}]}}
            destination = (Path(folder) / 'installed').resolve()
            voice.enqueue(destination, 'old verbose alert', 'old')
            (destination / 'muted').touch()
            legacy_command = str(destination / 'voice.py') + ' hook'
            original['hooks']['PostToolUseFailure'] = [{'hooks': [
                {'type': 'command', 'command': legacy_command},
                {'type': 'command', 'command': 'existing-tool-failure'}]}]
            original['hooks']['PermissionRequest'] = [{'hooks': [{'type': 'command', 'command': legacy_command}]}]
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
            self.assertIn('permission_prompt', installed['hooks']['Notification'][-1]['matcher'])
            self.assertNotIn('idle_prompt', installed['hooks']['Notification'][-1]['matcher'])
            self.assertEqual(len(installed['hooks']['StopFailure']), 1)
            self.assertEqual(len(installed['hooks']['TaskCompleted']), 1)
            self.assertEqual(installed['hooks']['PostToolUseFailure'][0]['hooks'][0]['command'], 'existing-tool-failure')
            self.assertEqual(len(installed['hooks']['PostToolUseFailure'][0]['hooks']), 1)
            self.assertTrue((destination / 'muted').exists())
            with voice.database(destination) as db:
                self.assertEqual(db.execute('SELECT status FROM alerts').fetchone()[0], 'cancelled')
            for kind in ['SubagentStop', 'PermissionRequest',
                         'PermissionDenied', 'Elicitation', 'SessionStart', 'SessionEnd']:
                self.assertNotIn(kind, installed['hooks'])
            self.assertEqual(len(list(Path(folder).glob('settings.json.voice-backup-*'))), 2)


if __name__ == '__main__':
    unittest.main()
