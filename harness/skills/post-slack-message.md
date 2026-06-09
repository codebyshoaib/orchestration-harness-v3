# post-slack-message

Send a message to the configured Slack channel. Use this from any skill or agent that needs to communicate with the user.

## Required env vars
- `SLACK_BOT_TOKEN`
- `SLACK_CHANNEL_ID`

## Post a message

```bash
CHANNEL_ID="$SLACK_CHANNEL_ID"  # or override with specific channel
MESSAGE_TEXT="Your message here"

curl -s -X POST "https://slack.com/api/chat.postMessage" \
  -H "Authorization: Bearer $SLACK_BOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"channel\": \"$CHANNEL_ID\",
    \"text\": \"$MESSAGE_TEXT\"
  }"
```

## Post a threaded reply

If responding to a specific message (e.g., acknowledging a user question), use the message timestamp to post in the thread:

```bash
CHANNEL_ID="$SLACK_CHANNEL_ID"
MESSAGE_TS="$THREAD_TS"  # the timestamp of the message to reply to
MESSAGE_TEXT="Your reply here"

curl -s -X POST "https://slack.com/api/chat.postMessage" \
  -H "Authorization: Bearer $SLACK_BOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"channel\": \"$CHANNEL_ID\",
    \"thread_ts\": \"$MESSAGE_TS\",
    \"text\": \"$MESSAGE_TEXT\"
  }"
```

## Post with rich formatting

Use blocks for richer message formatting:

```bash
curl -s -X POST "https://slack.com/api/chat.postMessage" \
  -H "Authorization: Bearer $SLACK_BOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"channel\": \"$SLACK_CHANNEL_ID\",
    \"blocks\": [
      {
        \"type\": \"section\",
        \"text\": {
          \"type\": \"mrkdwn\",
          \"text\": \"*Status Update*\nYour work is being processed. Ticket: <link>\"
        }
      }
    ]
  }"
```

## Check response

The API returns `{\"ok\": true, \"ts\": \"<timestamp>\"}` on success. Capture and check:

```bash
RESPONSE=$(curl -s -X POST "https://slack.com/api/chat.postMessage" ... )
if echo "$RESPONSE" | grep -q '"ok":true'; then
  echo "Message posted successfully"
else
  echo "Failed to post message: $RESPONSE"
fi
```
