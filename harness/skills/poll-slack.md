# poll-slack

Poll the configured Slack channel for messages since `last_sync_at` that mention `@agent`. If a message thread has no linked Notion ticket, create a stub ticket inline.

## Required env vars
- `SLACK_BOT_TOKEN`
- `SLACK_USER_TOKEN` (user token with `search:read` scope — required for search API)
- `SLACK_CHANNEL_ID`
- `NOTION_API_KEY`
- `NOTION_DATABASE_ID`

## Poll for messages mentioning @agent

Use `search.messages` to find all messages (top-level and replies) that mention the bot, across all threads:

```bash
# Overlap buffer (seconds). Slack's search index is NOT real-time — a message
# posted just before a tick may not be searchable until a later tick. We poll a
# window that reaches back PAST last_sync_at so late-indexed messages are still
# caught instead of being silently skipped once the watermark advances. Re-seeing
# an already-processed message is harmless: the per-message idempotency guard
# below skips it, and the event insert is INSERT OR IGNORE as a backstop.
OVERLAP_BUFFER_SECS=120
WINDOW_START_TS=$(sqlite3 harness/db/harness.db \
  "SELECT strftime('%s', last_sync_at) - $OVERLAP_BUFFER_SECS FROM sync_state WHERE id='global';")

# Derive the bot's own user ID at poll time — never hardcode it. A hardcoded ID
# silently matches zero messages once the bot or token is rotated.
BOT_USER_ID=$(curl -s -X POST https://slack.com/api/auth.test \
  -H "Authorization: Bearer $SLACK_BOT_TOKEN" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['user_id'])")

# search.messages requires the user token (search:read). -G + --data-urlencode encodes
# the <@BOT> mention so the angle brackets and @ are transmitted correctly.
# sort_dir=desc returns the NEWEST matches first, so recent mentions are always on
# the first page — with asc, once the bot has >count lifetime mentions the page is
# all-old and new mentions never appear, dropping them regardless of the window.
curl -s -G "https://slack.com/api/search.messages" \
  --data-urlencode "query=<@$BOT_USER_ID>" \
  --data "count=20&sort=timestamp&sort_dir=desc" \
  -H "Authorization: Bearer $SLACK_USER_TOKEN"
```

Filter results to `message.ts > $WINDOW_START_TS` (float comparison — Slack `ts` is epoch seconds with a microsecond fraction). For each matching message, extract:
- `channel.id` → `CHANNEL_ID`
- `ts` → `MESSAGE_TS`
- `thread_ts` (if present) → the root thread timestamp; use this as the thread identifier
- If no `thread_ts`, the message itself is the thread root: `THREAD_TS=$MESSAGE_TS`

## For each message mentioning `@agent`

0. **Idempotency guard — skip already-seen messages.** Because the poll window
   overlaps `last_sync_at`, a message can re-appear on a later tick. If an event
   for this message already exists, skip the message ENTIRELY — do not re-create
   the stub ticket and do not re-post the acknowledgment (those side effects are
   not protected by `INSERT OR IGNORE`):

   ```bash
   EVENT_ID="slack-$CHANNEL_ID-$MESSAGE_TS"
   SEEN=$(sqlite3 harness/db/harness.db "SELECT 1 FROM events WHERE id='$EVENT_ID';")
   if [ -n "$SEEN" ]; then
     continue   # already pending/processing/done — nothing to do
   fi
   ```

1. Check if a Notion entity is linked to this Slack thread:

```bash
SLACK_EXTERNAL_ID="$CHANNEL_ID/$MESSAGE_TS"
sqlite3 harness/db/harness.db \
  "SELECT e2.id, e2.external_id FROM links l
   JOIN entities e1 ON e1.id = l.entity_a
   JOIN entities e2 ON e2.id = l.entity_b
   WHERE e1.source='slack' AND e1.external_id='$SLACK_EXTERNAL_ID' AND e2.source='notion';"
```

2. If NO Notion entity is linked — create a stub Notion ticket:

```bash
STUB_TITLE="From Slack: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
curl -s -X POST "https://api.notion.com/v1/pages" \
  -H "Authorization: Bearer $NOTION_API_KEY" \
  -H "Notion-Version: 2022-06-28" \
  -H "Content-Type: application/json" \
  -d "{
    \"parent\": {\"database_id\": \"$NOTION_DATABASE_ID\"},
    \"properties\": {
      \"Task name\": {\"title\": [{\"text\": {\"content\": \"$STUB_TITLE\"}}]},
      \"Status\": {\"status\": {\"name\": \"Not started\"}},
      \"Slack Thread\": {\"url\": \"https://slack.com/archives/$CHANNEL_ID/p${MESSAGE_TS/./}\"}
    }
  }"
```

3. Create entities and link them (using entity-registry skill):
   - `slack` entity: `external_id = "$CHANNEL_ID/$MESSAGE_TS"`, `type = "thread"`
   - `notion` entity: `external_id = <new page id>`, `type = "ticket"`
   - Link: `slack_entity → notion_entity`, `relationship = "originated_from"`

4. Post acknowledgment to Slack:
   ```bash
   curl -s -X POST "https://slack.com/api/chat.postMessage" \
     -H "Authorization: Bearer $SLACK_BOT_TOKEN" \
     -H "Content-Type: application/json" \
     -d "{
       \"channel\": \"$CHANNEL_ID\",
       \"text\": \"Got your message! I'm looking into this. Check back soon for updates.\"
     }"
   ```

5. Insert event (use `INSERT OR IGNORE` — the event ID is deterministic, so a
   re-polled message collapses to a no-op rather than a duplicate row):
   - Event ID: `slack-$CHANNEL_ID-$MESSAGE_TS`
   - Event type: `message.tagged`
   - context_key: Notion entity ID
   - payload: full Slack message JSON
