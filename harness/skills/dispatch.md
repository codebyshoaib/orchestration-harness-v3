# dispatch

Read pending events, group by context_key, skip contexts with running sessions, and spawn subagent sessions.

## DB path
Always use: `harness/db/harness.db`

## Step 1: Read all pending context_keys, then fetch events per key

GROUP_CONCAT(payload) is unsafe because JSON payloads contain commas.
Use two queries: first get distinct context keys, then fetch full event rows per key.

```bash
# Query 1: which context_keys have pending events?
CONTEXT_KEYS=$(sqlite3 harness/db/harness.db \
  "SELECT DISTINCT context_key FROM events WHERE status='pending';")

# For each context_key (loop in agent logic):
# Query 2: fetch full event rows — payload is intact, no concatenation
sqlite3 harness/db/harness.db \
  "SELECT id, source, type, context_key, payload, received_at
   FROM events
   WHERE context_key='$CONTEXT_KEY' AND status='pending';"
```

## Step 2: For each context_key, check for running sessions

```bash
RUNNING=$(sqlite3 harness/db/harness.db \
  "SELECT id FROM sessions WHERE context_key='$CONTEXT_KEY' AND status='running';")
if [ -n "$RUNNING" ]; then
  echo "Session already running for $CONTEXT_KEY — skipping"
  continue
fi
```

## Step 3: Resolve context for the subagent

Gather the following for injection into the subagent prompt:
1. Notion ticket content — fetch via Notion API using the entity's `external_id`:
   ```bash
   NOTION_ENTITY=$(sqlite3 harness/db/harness.db \
     "SELECT external_id, url FROM entities WHERE id='$CONTEXT_KEY' AND source='notion';")
   PAGE_ID=$(echo "$NOTION_ENTITY" | cut -d'|' -f1)
   curl -s "https://api.notion.com/v1/pages/$PAGE_ID" \
     -H "Authorization: Bearer $NOTION_API_KEY" \
     -H "Notion-Version: 2022-06-28"
   ```
2. Linked entities (from entity-registry skill):
   ```bash
   sqlite3 harness/db/harness.db \
     "SELECT e.source, e.external_id, e.type, e.url FROM entities e
      JOIN links l ON (l.entity_a=e.id OR l.entity_b=e.id)
      WHERE (l.entity_a='$CONTEXT_KEY' OR l.entity_b='$CONTEXT_KEY')
        AND e.id != '$CONTEXT_KEY';"
   ```
3. Recent Slack thread (if a slack entity is linked) — fetch last 10 messages:
   ```bash
   curl -s "https://slack.com/api/conversations.replies?channel=$CHANNEL_ID&ts=$THREAD_TS&limit=10" \
     -H "Authorization: Bearer $SLACK_BOT_TOKEN"
   ```
4. Available skills list: sync-state, poll-notion, poll-slack, poll-github, entity-registry, dispatch
5. Triggering events (the pending event payloads for this context_key)

## Step 4: Create a session record

```bash
SESSION_ID="session-$(uuidgen | tr '[:upper:]' '[:lower:]')"
sqlite3 harness/db/harness.db \
  "INSERT INTO sessions (id, context_key, status, intent, created_at, updated_at)
   VALUES ('$SESSION_ID', '$CONTEXT_KEY', 'running', '$EVENT_TYPES', datetime('now'), datetime('now'));"
```

## Step 5: Mark events as processing

```bash
sqlite3 harness/db/harness.db \
  "UPDATE events SET status='processing' WHERE context_key='$CONTEXT_KEY' AND status='pending';"
```

## Step 6: Spawn subagent (via Agent tool)

Inject the following prompt into the Agent tool:

```
You are handling work item: <context_key>

Notion ticket: <notion_page_content>
Linked entities: <linked_entities_table>
Slack thread: <recent_slack_messages if applicable>
Triggering events: <event_types_and_payloads>
Session ID: <SESSION_ID>

Available skills (read and follow them as needed):
- harness/skills/sync-state.md
- harness/skills/poll-notion.md
- harness/skills/poll-slack.md
- harness/skills/poll-github.md
- harness/skills/entity-registry.md
- harness/skills/dispatch.md

Reason about what action is needed and act. When done:
1. Update Notion ticket status as your LAST action.
2. Update session record:
   sqlite3 harness/db/harness.db "UPDATE sessions SET status='completed', updated_at=datetime('now') WHERE id='<SESSION_ID>';"
3. Mark events as done:
   sqlite3 harness/db/harness.db "UPDATE events SET status='done', processed_at=datetime('now') WHERE context_key='<context_key>' AND status='processing';"

If you cannot proceed without human input:
1. Post a Slack message to the originating thread explaining what you need.
2. Set Notion ticket status to `Blocked`.
3. Update session: status='cancelled' (human will restart via @agent reply).
```

## Step 7: Handle subagent failure

If the Agent tool throws or the subagent does not update session status, mark the session cancelled and events back to pending:

```bash
sqlite3 harness/db/harness.db \
  "UPDATE sessions SET status='cancelled', updated_at=datetime('now') WHERE id='$SESSION_ID';"
sqlite3 harness/db/harness.db \
  "UPDATE events SET status='pending' WHERE context_key='$CONTEXT_KEY' AND status='processing';"
```
