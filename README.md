# Claude Voice for Mac

Hear when Claude Code needs your help, even when you are looking at another screen.
Your Mac speaks a short English message with its name, the project, and what happened.
Useful when you run Claude on several Macs. Free, local, and no API key needed.

Example: "Mac two. Project website. Session 12345678. Claude needs permission."

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

- Speaks permission prompts, requests for input, and API failures that end a turn.
- Uses the built-in Samantha English voice and the Mac's current audio output.
- Queues speech on each computer; different Macs may speak simultaneously.
- Suppresses identical alerts within 60 seconds and retains local history for 30 days.
- Preserves existing notification sounds and completion hooks.

The project folder and short session ID identify a job; no generated task title is
available. Event messages are shortened for speech. It does not interpret every
assistant response or detect every hung process, OS crash, or ordinary tool
failure. Background delivery depends on Claude Code emitting the relevant hook;
test the launch workflow you actually use.

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
