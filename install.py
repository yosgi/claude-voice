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
for event, matcher in [('Notification', 'permission_prompt|worker_permission_prompt|agent_needs_input|elicitation_dialog|elicitation_url_dialog'), ('StopFailure', None)]:
    entries = data.setdefault('hooks', {}).setdefault(event, [])
    # Replace only this installer's previous handler, including after a computer rename.
    for entry in entries:
        entry['hooks'] = [h for h in entry.get('hooks', []) if str(target) not in h.get('command', '')]
    entries[:] = [entry for entry in entries if entry.get('hooks')]
    entry = {'hooks': [{'type': 'command', 'command': command, 'timeout': 10}]}
    if matcher:
        entry['matcher'] = matcher
    entries.append(entry)
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
