"""
Slack Socket Mode daemon — receives app_mention events and writes them to harness.db.

Replaces poll-slack.md. Mirrors steps 0-5 of that skill exactly.

Required env vars:
  SLACK_BOT_TOKEN    xoxb-...
  SLACK_APP_TOKEN    xapp-...  (Socket Mode app-level token)
  SLACK_CHANNEL_ID   single channel to monitor
  NOTION_API_KEY
  NOTION_DATABASE_ID

Run:
  python harness/daemon/slack_daemon.py
"""

import logging
import os
import sqlite3
import uuid
import json
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

load_dotenv("harness/.env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

DB_PATH = "harness/db/harness.db"
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]
SLACK_CHANNEL_ID = os.environ["SLACK_CHANNEL_ID"]
NOTION_API_KEY = os.environ["NOTION_API_KEY"]
NOTION_DATABASE_ID = os.environ["NOTION_DATABASE_ID"]

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

app = App(token=SLACK_BOT_TOKEN)


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def find_notion_entity_for_slack_thread(conn: sqlite3.Connection, slack_external_id: str):
    row = conn.execute(
        """
        SELECT e2.id, e2.external_id FROM links l
        JOIN entities e1 ON e1.id = l.entity_a
        JOIN entities e2 ON e2.id = l.entity_b
        WHERE e1.source='slack' AND e1.external_id=? AND e2.source='notion'
        """,
        (slack_external_id,),
    ).fetchone()
    return row


def create_notion_stub(channel_id: str, message_ts: str) -> str | None:
    ts_clean = message_ts.replace(".", "")
    title = f"From Slack: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}"
    payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": {
            "Task name": {"title": [{"text": {"content": title}}]},
            "Status": {"status": {"name": "Not started"}},
            "Slack Thread": {
                "url": f"https://slack.com/archives/{channel_id}/p{ts_clean}"
            },
        },
    }
    try:
        resp = requests.post(
            "https://api.notion.com/v1/pages",
            headers=NOTION_HEADERS,
            json=payload,
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()["id"]
    except Exception as exc:
        log.error("Failed to create Notion stub: %s", exc)
        return None


def insert_entities_and_link(
    conn: sqlite3.Connection,
    channel_id: str,
    message_ts: str,
    notion_page_id: str,
) -> str:
    now = datetime.now(timezone.utc).isoformat()
    slack_external_id = f"{channel_id}/{message_ts}"
    slack_entity_id = str(uuid.uuid4())
    notion_entity_id = str(uuid.uuid4())

    conn.execute(
        "INSERT OR IGNORE INTO entities (id, source, external_id, type, url, created_at) VALUES (?,?,?,?,?,?)",
        (
            slack_entity_id,
            "slack",
            slack_external_id,
            "thread",
            f"https://slack.com/archives/{channel_id}/p{message_ts.replace('.', '')}",
            now,
        ),
    )
    # Re-fetch in case the entity already existed (INSERT OR IGNORE)
    row = conn.execute(
        "SELECT id FROM entities WHERE source='slack' AND external_id=?",
        (slack_external_id,),
    ).fetchone()
    slack_entity_id = row["id"]

    conn.execute(
        "INSERT OR IGNORE INTO entities (id, source, external_id, type, url, created_at) VALUES (?,?,?,?,?,?)",
        (
            notion_entity_id,
            "notion",
            notion_page_id,
            "ticket",
            f"https://www.notion.so/{notion_page_id.replace('-', '')}",
            now,
        ),
    )
    row = conn.execute(
        "SELECT id FROM entities WHERE source='notion' AND external_id=?",
        (notion_page_id,),
    ).fetchone()
    notion_entity_id = row["id"]

    conn.execute(
        "INSERT OR IGNORE INTO links (entity_a, entity_b, relationship, created_at, created_by) VALUES (?,?,?,?,?)",
        (slack_entity_id, notion_entity_id, "originated_from", now, "slack-daemon"),
    )
    conn.commit()
    return notion_entity_id


@app.event("app_mention")
def handle_app_mention(event, say, client):
    channel_id = event.get("channel")
    message_ts = event.get("ts")
    thread_ts = event.get("thread_ts", message_ts)

    # Only process the monitored channel
    if channel_id != SLACK_CHANNEL_ID:
        log.debug("Ignoring mention in unmonitored channel %s", channel_id)
        return

    event_id = f"slack-{channel_id}-{message_ts}"

    with get_db() as conn:
        # Step 0: idempotency guard
        seen = conn.execute(
            "SELECT 1 FROM events WHERE id=?", (event_id,)
        ).fetchone()
        if seen:
            log.info("Already seen %s — skipping", event_id)
            return

        # Step 1: find linked Notion entity
        slack_external_id = f"{channel_id}/{thread_ts}"
        notion_row = find_notion_entity_for_slack_thread(conn, slack_external_id)

        if notion_row:
            notion_entity_id = notion_row["id"]
            log.info("Found existing Notion entity %s", notion_entity_id)
        else:
            # Step 2: create Notion stub
            notion_page_id = create_notion_stub(channel_id, thread_ts)
            if not notion_page_id:
                log.error("Skipping event %s — Notion stub creation failed", event_id)
                return

            # Step 3: insert entities and link
            notion_entity_id = insert_entities_and_link(
                conn, channel_id, thread_ts, notion_page_id
            )
            log.info("Created Notion stub %s linked to Slack thread", notion_page_id)

        # Step 4: acknowledge in Slack
        try:
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text="Got your message! I'm looking into this. Check back soon for updates.",
            )
        except Exception as exc:
            log.warning("Failed to post Slack ack: %s", exc)

        # Step 5: insert event
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT OR IGNORE INTO events (id, source, type, context_key, payload, status, received_at)
            VALUES (?, 'slack', 'message.tagged', ?, ?, 'pending', ?)
            """,
            (event_id, notion_entity_id, json.dumps(event), now),
        )
        conn.commit()
        log.info("Inserted event %s → context_key %s", event_id, notion_entity_id)


if __name__ == "__main__":
    log.info("Starting Slack Socket Mode daemon (monitoring channel %s)", SLACK_CHANNEL_ID)
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
