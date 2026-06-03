# e2e-test

Run E2E tests against the workspace app using Chrome DevTools MCP. Called by subagents after implementation, before opening a PR.

## Inputs (held in subagent working context)

- `TEST_CASES`: list of test cases defined during Step A planning, each with:
  - `name`: short label (e.g. "Todo item appears after creation")
  - `steps`: list of Chrome DevTools MCP actions to perform
  - `expected`: what to assert (element visible, text present, network response, etc.)
- `SESSION_ID`: the current session ID (used for screenshot filenames)
- `PAGE_ID`: the Notion page ID of the current ticket

## Phase 1: Start dev server

```bash
cd harness/workspace
npm run dev > /tmp/nextjs-dev.log 2>&1 &
DEV_PID=$!
echo $DEV_PID > /tmp/nextjs-dev.pid

# Poll until ready (up to 30s)
for i in $(seq 1 30); do
  curl -s http://localhost:3000 > /dev/null 2>&1 && break
  sleep 1
done
curl -s http://localhost:3000 > /dev/null 2>&1 || echo "WARN: server may not be ready"
```

If the dev server is not responding after 30s, treat this as a test failure and enter the fix loop (Phase 3) starting at attempt 1.

## Phase 2: Run test cases

Set `attempt = 1` before entering this phase for the first time.

Before running any Chrome DevTools MCP tools, load them:
```
ToolSearch: select:mcp__chrome-devtools__new_page,mcp__chrome-devtools__navigate_page,mcp__chrome-devtools__take_screenshot,mcp__chrome-devtools__wait_for,mcp__chrome-devtools__click,mcp__chrome-devtools__type_text,mcp__chrome-devtools__get_console_message,mcp__chrome-devtools__list_console_messages,mcp__chrome-devtools__close_page
```

Before running the first test case, create the screenshots directory.
(Run from the project root. CWD must be the project root for this path to resolve correctly.)
```bash
mkdir -p harness/e2e-screenshots/$SESSION_ID
```

For each test case in `TEST_CASES`:

1. Open a new page: `mcp__chrome-devtools__new_page`
2. Navigate to `http://localhost:3000` (or the URL specified in the test case): `mcp__chrome-devtools__navigate_page`
3. Execute each step in the test case's `steps` list using the appropriate Chrome DevTools MCP tool
4. Assert the expected outcome. If assertion fails, record the failure reason.
5. Capture console output before closing the page: `mcp__chrome-devtools__list_console_messages` — store the result as `console_output`.
6. Capture a screenshot regardless of pass/fail:
   ```
   mcp__chrome-devtools__take_screenshot → save to harness/e2e-screenshots/$SESSION_ID/<test-name>-attempt-<attempt>.png
   ```
   If the tool accepts an output path parameter, pass `harness/e2e-screenshots/$SESSION_ID/<test-name>-attempt-<attempt>.png` directly. If it returns base64 data, decode and write to disk: `echo '<base64>' | base64 -d > harness/e2e-screenshots/$SESSION_ID/<test-name>-attempt-<attempt>.png`
7. Close the page: `mcp__chrome-devtools__close_page`

Collect results: list of `{name, passed: bool, failure_reason, screenshot_path, console_output}`.

## Phase 3: Fix loop (max 5 attempts)

If all test cases passed → skip to Phase 4.

If any test cases failed and `attempt < 5`:
1. Analyse: failure reason + stored `console_output` from Phase 2 results + screenshot
2. Fix the relevant source files in `harness/workspace/src/` (never modify skill files)
3. If the fix changes server-side code, restart the dev server:
   ```bash
   kill $(cat /tmp/nextjs-dev.pid) 2>/dev/null
   cd harness/workspace && npm run dev > /tmp/nextjs-dev.log 2>&1 &
   echo $! > /tmp/nextjs-dev.pid
   # Poll until ready (same 30s loop as Phase 1)
   for i in $(seq 1 30); do
     curl -s http://localhost:3000 > /dev/null 2>&1 && break
     sleep 1
   done
   curl -s http://localhost:3000 > /dev/null 2>&1 || echo "WARN: server may not be ready after restart"
   ```
4. Increment `attempt` by 1, then re-enter Phase 2 (only if `attempt < 5`).

If `attempt == 5` and tests still fail → proceed to Phase 4 with status `failed`.

## Phase 4: Teardown + report

```bash
kill $(cat /tmp/nextjs-dev.pid) 2>/dev/null
rm -f /tmp/nextjs-dev.pid /tmp/nextjs-dev.log
```

Return status to the caller:
- `passed` — all test cases green; `screenshots`: list of screenshot paths
- `failed` — `failed_cases`: list of `{name, failure_reason, screenshot_path}`; `console_errors`: final attempt's console output

## Phase 5: Upload screenshots to Notion

For each screenshot captured during all attempts, upload to Notion and attach as an image block.

For each `screenshot_path` in the collected screenshots list: run Step 5a (substituting `screenshot_path` for the file path), capture the resulting `UPLOAD_ID`, then run Step 5b substituting `UPLOAD_ID` and the test case metadata for that screenshot.

### 5a: Upload the file

```bash
# Create upload
UPLOAD=$(curl -s -X POST "https://api.notion.com/v1/file_uploads" \
  -H "Authorization: Bearer $NOTION_API_KEY" \
  -H "Notion-Version: 2022-06-28" \
  -H "Content-Type: application/json" \
  -d '{"content_type": "image/png"}')
UPLOAD_ID=$(echo "$UPLOAD" | jq -r '.id')

# Send file bytes
curl -s -X POST "https://api.notion.com/v1/file_uploads/$UPLOAD_ID/send" \
  -H "Authorization: Bearer $NOTION_API_KEY" \
  -H "Notion-Version: 2022-06-28" \
  -F "file=@<screenshot_path>"
```

### 5b: Append heading + image blocks to Notion ticket

```bash
# Build the children array: one heading block + one image block per test case
curl -s -X PATCH "https://api.notion.com/v1/blocks/$PAGE_ID/children" \
  -H "Authorization: Bearer $NOTION_API_KEY" \
  -H "Notion-Version: 2022-06-28" \
  -H "Content-Type: application/json" \
  -d '{
    "children": [
      {
        "type": "heading_2",
        "heading_2": {
          "rich_text": [{"text": {"content": "E2E Test Results — <passed|failed>"}}]
        }
      },
      {
        "paragraph": {
          "rich_text": [{"text": {"content": "<test-name>: ✅ or ❌ <failure_reason if failed>"}}]
        }
      },
      {
        "image": {
          "type": "file",
          "file": {
            "type": "uploaded_file",
            "uploaded_file": {"id": "<UPLOAD_ID>"}
          }
        }
      }
    ]
  }'
```

Repeat the paragraph + image pair for each test case.
