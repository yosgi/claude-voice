#!/usr/bin/env python3
"""English Claude Code alerts using macOS speech; Python standard library only."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time

ATTENTION = {'permission_prompt', 'worker_permission_prompt', 'agent_needs_input',
             'elicitation_dialog', 'elicitation_url_dialog'}


def clean(value, limit=240):
    return ' '.join(str(value or '').split())[:limit]


def render(event, computer):
    kind = event.get('hook_event_name')
    if kind == 'Notification':
        notification = event.get('notification_type')
        if notification not in ATTENTION:
            return None
        reason = ('Claude needs permission.' if 'permission' in notification
                  else 'Claude needs your input.')
        detail = clean(event.get('message'))
    elif kind == 'StopFailure':
        reason = 'Claude stopped because of ' + clean(event.get('error', 'an API error')).replace('_', ' ') + '.'
        detail = clean(event.get('error_details') or event.get('last_assistant_message'))
    else:
        return None
    project = clean(Path(event.get('cwd') or '.').name, 60) or 'Unknown project'
    # Project and short session ID distinguish concurrent jobs without reading transcripts.
    session = clean(event.get('session_id'), 8)
    label = f'{computer}. Project {project}.'
    if session:
        label += f' Session {session}.'
    return clean(f'{label} {reason} {detail}', 480)


def database(state):
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(state / 'alerts.sqlite', timeout=15)
    db.execute('CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY, created REAL, text TEXT, fingerprint TEXT, status TEXT)')
    db.commit()
    return db


def enqueue(state, message, fingerprint):
    with database(state) as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM alerts WHERE fingerprint=? AND created>?',
                      (fingerprint, time.time() - 60)).fetchone():
            return False
        db.execute('INSERT INTO alerts(created,text,fingerprint,status) VALUES(?,?,?,?)',
                   (time.time(), message, fingerprint, 'pending'))
        db.execute('DELETE FROM alerts WHERE created<? AND status != ?', (time.time()-30*86400, 'pending'))
    return True


def work(state):
    # Every enqueuer starts a worker. Waiting on the lock avoids a lost-wakeup race.
    with (state / 'speech.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with database(state) as db:
            while True:
                row = db.execute("SELECT id,text FROM alerts WHERE status='pending' ORDER BY id LIMIT 1").fetchone()
                if row is None:
                    break
                try:
                    result = subprocess.run(['/usr/bin/say', '-v', 'Samantha', row[1]], timeout=90, check=False)
                    status = 'spoken' if result.returncode == 0 else 'failed'
                except (OSError, subprocess.TimeoutExpired):
                    status = 'failed'
                db.execute('UPDATE alerts SET status=? WHERE id=?', (status, row[0]))
                db.commit()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['hook', 'worker', 'test', 'history', 'replay'])
    parser.add_argument('--state', type=Path, default=Path.home() / 'Library/Application Support/ClaudeVoice')
    parser.add_argument('--computer', default=socket.gethostname().split('.')[0])
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    state = args.state.resolve()
    if args.action == 'worker':
        work(state)
        return
    if args.action in ('history', 'replay'):
        with database(state) as db:
            rows = db.execute('SELECT created,text,status FROM alerts ORDER BY id DESC LIMIT 20').fetchall()
        if args.action == 'history':
            for stamp, message, status in reversed(rows):
                print(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stamp)), status, message)
            return
        if not rows:
            print('No alerts to replay.')
            return
        message = rows[0][1]
        fingerprint = 'replay:' + str(time.time_ns())
    else:
        event = ({'hook_event_name': 'Notification', 'notification_type': 'permission_prompt',
                  'cwd': 'voice-test', 'message': 'This is a test. English voice alerts are working.'}
                 if args.action == 'test' else json.load(sys.stdin))
        message = render(event, clean(args.computer, 60))
        if message is None:
            return
        fingerprint = json.dumps([event.get('session_id'), event.get('cwd'), message])
    if args.dry_run:
        print(message)
        return
    if enqueue(state, message, fingerprint):
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'worker', '--state', str(state)],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, sqlite3.Error) as exc:
        # Hook failures must not interrupt Claude's work.
        print(f'Claude voice: {exc}', file=sys.stderr)
