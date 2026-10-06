#!/usr/bin/env python3
"""Add voice hooks while preserving all existing Claude settings."""
import argparse
import json
from pathlib import Path
import shlex
import shutil
import sys
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--computer', required=True, help='Spoken name, for example Mac one')
parser.add_argument('--settings', type=Path, default=Path.home()/'.claude/settings.json')
parser.add_argument('--destination', type=Path, default=Path.home()/'Library/Application Support/ClaudeVoice')
args = parser.parse_args()
settings = args.settings.resolve()
destination = args.destination.resolve()
data = json.loads(settings.read_text()) if settings.exists() else {}
if data.get('disableAllHooks'):
    raise SystemExit('Claude hooks are disabled. Enable them before installing voice alerts.')
destination.mkdir(parents=True, exist_ok=True, mode=0o700)
target = destination/'voice.py'
shutil.copy2(Path(__file__).with_name('voice.py'), target)
command = ' '.join(shlex.quote(s) for s in [sys.executable, str(target), 'hook', '--state', str(destination), '--computer', args.computer])
# Remove all previous versions of our hooks, preserving unrelated handlers.
for event, entries in list(data.setdefault('hooks', {}).items()):
    for entry in entries:
        entry['hooks'] = [h for h in entry.get('hooks', []) if str(target) not in h.get('command', '')]
    entries[:] = [entry for entry in entries if entry.get('hooks')]
    if not entries:
        del data['hooks'][event]
for event in ['Notification', 'Stop', 'StopFailure', 'TaskCompleted']:
    entry = {'hooks': [{'type': 'command', 'command': command, 'timeout': 10}]}
    if event == 'Notification':
        entry['matcher'] = 'permission_prompt|worker_permission_prompt|agent_needs_input|elicitation_dialog|elicitation_url_dialog|agent_completed|quota_auto_resume_stale|quota_auto_resume_disabled'
    data['hooks'].setdefault(event, []).append(entry)
# Cancel old queued verbose messages, retain history and the current mute state.
import voice
voice.control(destination, 'stop')
settings.parent.mkdir(parents=True, exist_ok=True)
backup = None
if settings.exists():
    backup = settings.with_name(settings.name + '.voice-backup-' + str(time.time_ns()))
    shutil.copy2(settings, backup)
temporary = settings.with_name(settings.name + '.voice-tmp')
temporary.write_text(json.dumps(data, indent=2) + '\n')
if settings.exists():
    shutil.copymode(settings, temporary)
else:
    temporary.chmod(0o600)
temporary.replace(settings)
print('Voice hooks installed:', settings)
if backup:
    print('Previous settings saved:', backup)
print('Restart Claude sessions to load the new hooks.')
