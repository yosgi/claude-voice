#!/usr/bin/env python3
"""English Claude Code alerts using macOS speech; Python standard library only."""
import argparse
import fcntl
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time

def clean(value, limit=240):
    return ' '.join(str(value or '').split())[:limit]


def category(event):
    kind = event.get('hook_event_name')
    if kind == 'Notification':
        notification = event.get('notification_type')
        if notification in ('permission_prompt', 'worker_permission_prompt'):
            return 'permission', 'Claude needs permission.', 300
        if notification in ('agent_needs_input', 'elicitation_dialog', 'elicitation_url_dialog',
                            'quota_auto_resume_stale'):
            return 'input', 'Claude needs your input.', 300
        if notification == 'agent_completed':
            # This event can also represent failure; do not promise success.
            return 'completion', 'Claude background task ended.', 30
        if notification == 'quota_auto_resume_disabled':
            return 'api:usage_limit', 'Claude stopped at a usage limit.', 300
        return None
    if kind == 'Stop':
        if event.get('stop_hook_active'):
            return None
        return 'completion', 'Claude finished responding.', 30
    if kind == 'TaskCompleted':
        return 'completion', 'Claude task completed.', 30
    if kind == 'StopFailure':
        error = str(event.get('error') or 'unknown')
        reasons = {
            'rate_limit': 'a rate limit', 'overloaded': 'the API is overloaded',
            'authentication_failed': 'authentication failed',
            'billing_error': 'a billing error', 'server_error': 'a server error',
            'max_output_tokens': 'the output limit was reached',
        }
        return 'api:' + error, 'Claude stopped: ' + reasons.get(error, 'an API error') + '.', 300
    return None


def render(event, computer):
    alert = category(event)
    if alert is None:
        return None
    project = clean(Path(event.get('cwd') or '.').name, 40) or 'Unknown project'
    # Speak one short status, not raw errors, commands, or full final responses.
    return f'{clean(computer, 40)}. Project {project}. {alert[1]}'


def alert_key(event, computer):
    alert = category(event)
    if alert is None:
        return None
    # Coalesce equivalent event sources and changing error details per session.
    return json.dumps([computer, event.get('cwd'), event.get('session_id'), alert[0]])


def database(state):
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(state / 'alerts.sqlite', timeout=15)
    db.execute('CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY, created REAL, text TEXT, fingerprint TEXT, status TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS merged_alerts (alert_id INTEGER PRIMARY KEY, repeats INTEGER NOT NULL)')
    db.commit()
    return db


def enqueue(state, message, fingerprint, cooldown=60):
    with database(state) as db:
        db.execute('BEGIN IMMEDIATE')
        if (state / 'muted').exists():
            return False
        duplicate = db.execute(
            "SELECT id FROM alerts WHERE fingerprint=? AND created>? AND status IN ('pending','spoken') ORDER BY id DESC LIMIT 1",
            (fingerprint, time.time() - cooldown)).fetchone()
        if duplicate:
            db.execute('INSERT INTO merged_alerts(alert_id,repeats) VALUES(?,1) '
                       'ON CONFLICT(alert_id) DO UPDATE SET repeats=repeats+1', (duplicate[0],))
            return False
        db.execute('INSERT INTO alerts(created,text,fingerprint,status) VALUES(?,?,?,?)',
                   (time.time(), message, fingerprint, 'pending'))
        # Limit backlog and expire stale reminders instead of reading an old flood.
        db.execute("UPDATE alerts SET status='cancelled' WHERE status='pending' AND created<?", (time.time()-300,))
        db.execute("UPDATE alerts SET status='cancelled' WHERE status='pending' AND id NOT IN (SELECT id FROM alerts WHERE status='pending' ORDER BY id DESC LIMIT 20)")
        db.execute('DELETE FROM alerts WHERE created<? AND status != ?', (time.time()-30*86400, 'pending'))
        db.execute('DELETE FROM merged_alerts WHERE alert_id NOT IN (SELECT id FROM alerts)')
    return True


def cancellation(state):
    marker = state / 'cancel'
    return marker.read_text() if marker.exists() else ''


def control(state, action):
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with database(state) as db:
        db.execute('BEGIN IMMEDIATE')
        if action == 'unmute':
            (state / 'muted').unlink(missing_ok=True)
            print('Voice alerts resumed.')
            return
        if action == 'mute':
            (state / 'muted').touch()
        (state / 'cancel').write_text(str(time.time_ns()))
        db.execute("UPDATE alerts SET status='cancelled' WHERE status='pending'")
    print('Voice alerts paused.' if action == 'mute' else 'Current speech and queued alerts stopped.')


def speak(state, message, generation):
    if (state / 'muted').exists() or cancellation(state) != generation:
        return 'cancelled'
    with subprocess.Popen(['/usr/bin/say', '-v', 'Samantha', message]) as speech:
        deadline = time.monotonic() + 90
        while speech.poll() is None:
            if (state / 'muted').exists() or cancellation(state) != generation or time.monotonic() > deadline:
                speech.terminate()
                try:
                    speech.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    speech.kill()
                    speech.wait()
                return 'cancelled'
            time.sleep(0.1)
        return 'spoken' if speech.returncode == 0 else 'failed'


def work(state):
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Every hook starts a worker. Waiting on the lock avoids a lost-wakeup race.
    with (state / 'speech.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        generation = cancellation(state)
        with database(state) as db:
            while True:
                if (state / 'muted').exists() or cancellation(state) != generation:
                    break
                db.execute("UPDATE alerts SET status='cancelled' WHERE status='pending' AND created<?", (time.time()-300,))
                db.commit()
                row = db.execute("SELECT id,text FROM alerts WHERE status='pending' ORDER BY id LIMIT 1").fetchone()
                if row is None:
                    break
                try:
                    status = speak(state, row[1], generation)
                except (OSError, subprocess.TimeoutExpired):
                    status = 'failed'
                db.execute("UPDATE alerts SET status=? WHERE id=? AND status='pending'", (status, row[0]))
                db.commit()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['hook', 'worker', 'test', 'history', 'replay', 'stop', 'mute', 'unmute'])
    parser.add_argument('--state', type=Path, default=Path.home() / 'Library/Application Support/ClaudeVoice')
    parser.add_argument('--computer', default=socket.gethostname().split('.')[0])
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    state = args.state.resolve()
    if args.action in ('stop', 'mute', 'unmute'):
        control(state, args.action)
        return
    if args.action == 'worker':
        work(state)
        return
    if args.action in ('history', 'replay'):
        with database(state) as db:
            rows = db.execute('SELECT a.created,a.text,a.status,COALESCE(m.repeats,0) FROM alerts a LEFT JOIN merged_alerts m ON m.alert_id=a.id ORDER BY a.id DESC LIMIT 20').fetchall()
        if args.action == 'history':
            for stamp, message, status, repeats in reversed(rows):
                print(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stamp)), status, message,
                      f'({repeats} repeats merged)' if repeats else '')
            return
        if not rows:
            print('No alerts to replay.')
            return
        message = rows[0][1]
        fingerprint = 'replay:' + str(time.time_ns())
        cooldown = 0
    else:
        event = ({'hook_event_name': 'Notification', 'notification_type': 'permission_prompt',
                  'cwd': 'voice-test', 'message': 'This is a test. English voice alerts are working.'}
                 if args.action == 'test' else json.load(sys.stdin))
        message = render(event, clean(args.computer, 60))
        if message is None:
            return
        fingerprint = alert_key(event, args.computer)
        cooldown = category(event)[2]
        if args.action == 'test':
            fingerprint = 'test:' + str(time.time_ns())
    if args.dry_run:
        print(message)
        return
    if (state / 'muted').exists():
        if args.action != 'hook':
            print('Voice alerts are paused. Run unmute to resume.')
        return
    accepted = enqueue(state, message, fingerprint, cooldown)
    if args.action in ('test', 'replay'):
        # Manual tests stay attached so their completion can be verified.
        work(state)
    elif accepted:
        # Remain fully detached so speech survives non-interactive CLI teardown.
        # Keep diagnostics instead of silently discarding worker failures.
        with (state / 'worker.log').open('a') as log:
            subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'worker', '--state', str(state)],
                             stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                             start_new_session=True)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, sqlite3.Error) as exc:
        # Hook failures must not interrupt Claude's work.
        print(f'Claude voice: {exc}', file=sys.stderr)
