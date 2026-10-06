# Claude Voice for Mac

Hear when Claude Code needs your help, even when you are looking at another screen.
Your Mac speaks a short English message with its name, the project, and what happened.
Useful when you run Claude on several Macs. Free, local, and no API key needed.

Example: "Mac two. Project website. Claude needs permission."

## Install on each Mac

You need a Mac with Python 3, Git, and a current version of Claude Code.
No GitHub login is needed to download this public repository.

```bash
git clone https://github.com/yosgi/claude-voice.git "$HOME/claude-voice"
cd "$HOME/claude-voice"
bash install.sh "Mac two"
```

Use `"Mac one"`, `"Mac two"`, and `"Mac three"` to distinguish your computers.
Omit the name to use the Mac's Computer Name. Restart Claude Code sessions after
installing. The installer preserves existing settings and hooks, saves a backup,
and copies the runtime to `~/Library/Application Support/ClaudeVoice`.

## Update

```bash
cd "$HOME/claude-voice"
git pull --ff-only
bash install.sh "Mac two"
```

Use the same computer name as before, then restart Claude Code sessions.
Pulling alone downloads the source; rerunning the installer updates the runtime.

## Test, history, and replay

```bash
python3 "$HOME/Library/Application Support/ClaudeVoice/voice.py" test --computer "Mac two"
python3 "$HOME/Library/Application Support/ClaudeVoice/voice.py" history
python3 "$HOME/Library/Application Support/ClaudeVoice/voice.py" replay
```

## Behavior

- Speaks short completion, permission, input, and API-stop reminders.
- Ignores ordinary progress, tool failures, subagent chatter, and session start/end.
- Uses actual permission notifications, so automatic tool checks do not cause speech.
- Reads one short status sentence, never long errors or full final responses.
- Merges equivalent reminders from the same project and session: completion within
  30 seconds, permission/input/API errors within 5 minutes. Changing error details
  do not create another alert for the same API error type.
- Queues at most 20 short alerts and discards alerts older than 5 minutes.
- Uses the built-in Samantha English voice and the Mac's current audio output.
- Keeps local history for 30 days, including counts of merged reminders.
- Preserves existing notification sounds and unrelated Claude hooks.

"Finished responding" means a turn ended; it does not guarantee the whole task
succeeded. A background task can also end in failure. Permissions and input are
announced when Claude emits the relevant notification (often after about six
seconds). Idle nudges after a finished response are ignored. Separate sessions
can still produce separate reminders; your Mac plays them one at a time.

Upgrading removes this tool's old verbose hooks and cancels the old speech queue.
Your paused/unpaused state is preserved: an upgrade never automatically unmutes.
After updating, restart Claude Code sessions to load the smaller hook list.

If there is no voice, check whether it is paused, run the manual test above, and
check `history` or `~/Library/Application Support/ClaudeVoice/worker.log` for errors.
The tool cannot detect an OS crash or a process that hangs without emitting an event.

## Stop or pause speech

Stop the current message and clear queued messages (future alerts still play):

```bash
python3 "$HOME/Library/Application Support/ClaudeVoice/voice.py" stop
```

Pause voice alerts until you resume them, including across restarts:

```bash
python3 "$HOME/Library/Application Support/ClaudeVoice/voice.py" mute
```

Resume voice alerts:

```bash
python3 "$HOME/Library/Application Support/ClaudeVoice/voice.py" unmute
```

These commands affect this Mac's voice alerts. Existing Claude notification
sounds remain enabled. Alerts received while paused are not replayed on resume.

## Uninstall

Remove only the hook commands referring to `ClaudeVoice` from
`~/.claude/settings.json`, then restart Claude Code. Keep or delete the local
runtime and history as desired. Alternatively, restore the installer backup if
you have made no subsequent settings changes.

## Validation

```bash
python3 -m unittest -v
```

See the [Claude Code hook reference](https://code.claude.com/docs/en/hooks).

## License

MIT. Anyone may use, share, and modify this tool. See [LICENSE](LICENSE).
