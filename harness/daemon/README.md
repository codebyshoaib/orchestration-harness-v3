# Slack Socket Mode Daemon

Receives `app_mention` events in real time and writes them to `harness/db/harness.db`.
Replaces the `poll-slack` step in the tick sequence.

## Setup

```bash
cd harness/daemon
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

Add `SLACK_APP_TOKEN` to `harness/.env` (see `.env.example`).  
This is the `xapp-` app-level token — different from `SLACK_BOT_TOKEN`.  
Enable Socket Mode in your Slack app settings and generate it there.

## Run manually (dev/test)

```bash
cd /home/shoaib/Taleemabad/orchestration-harness-v2
harness/daemon/venv/bin/python harness/daemon/slack_daemon.py
```

## Install as a systemd user service

```bash
cp harness/daemon/slack-daemon.service ~/.config/systemd/user/slack-daemon.service
systemctl --user daemon-reload
systemctl --user enable --now slack-daemon
```

Check status:
```bash
systemctl --user status slack-daemon
journalctl --user -u slack-daemon -f
```

Restart after a code change:
```bash
systemctl --user restart slack-daemon
```

## Slack app permissions required

Bot token scopes (`SLACK_BOT_TOKEN`):
- `app_mentions:read`
- `chat:write`
- `channels:history` (to read thread context)

Socket Mode requires an app-level token (`SLACK_APP_TOKEN`) with the `connections:write` scope.

## What it does per mention

1. Idempotency check — skips if event already in DB
2. Looks up a linked Notion entity for the Slack thread
3. Creates a Notion stub ticket if none exists
4. Posts an acknowledgment to the Slack thread
5. Inserts a `pending` event into `harness/db/harness.db`

The next `/loop` tick picks up the event and dispatches an agent session.
