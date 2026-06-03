# Setup Wizard

Guide the team member through each phase in order. Before each phase, check whether it can be skipped by inspecting observable state (filesystem, process, API). Stop immediately on any failure — print the phase name, error, and exact remediation steps.

---

## Phase 1: Clone Harness

**Skip if:** you are already running inside the cloned harness repo (i.e., `harness/skills/setup.md` exists at the current path).

If not already inside the repo:
1. Ask the user: "What is the harness repo URL?"
2. Run:
   ```bash
   git clone <url> orchestration-harness-v2
   cd orchestration-harness-v2
   ```
3. Confirm `harness/skills/setup.md` now exists. If not, stop: "Clone succeeded but expected files not found — check the repo URL."

---

## Phase 2: Configure Env

**Skip if:** `harness/.env` exists AND all tokens pass full validation (run validation checks below — if all pass, print "Env already configured ✓" and move on).

Steps:
1. Print: "Let's configure your credentials. I'll ask for each value and validate it before writing the file."
2. For each variable in `harness/.env.example`, prompt the user: "Enter value for `<VAR_NAME>`:" (show the comment from `.env.example` as context).
3. After collecting all values, validate each service:

**Notion validation:**
```bash
# Validate token
curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $NOTION_API_KEY" \
  -H "Notion-Version: 2022-06-28" \
  https://api.notion.com/v1/users/me
# Expect: 200
```
```bash
# Validate database ID
curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $NOTION_API_KEY" \
  -H "Notion-Version: 2022-06-28" \
  https://api.notion.com/v1/databases/$NOTION_DATABASE_ID
# Expect: 200
```
```bash
# Validate agent user ID
curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $NOTION_API_KEY" \
  -H "Notion-Version: 2022-06-28" \
  https://api.notion.com/v1/users/$NOTION_AGENT_USER_ID
# Expect: 200
```

**Slack validation:**
```bash
curl -s -X POST https://slack.com/api/auth.test \
  -H "Authorization: Bearer $SLACK_BOT_TOKEN" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('ok' if d['ok'] else d['error'])"
# Expect: ok
```
```bash
curl -s "https://slack.com/api/conversations.info?channel=$SLACK_CHANNEL_ID" \
  -H "Authorization: Bearer $SLACK_BOT_TOKEN" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('ok' if d['ok'] else d['error'])"
# Expect: ok
```

**GitHub validation:**
```bash
curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  https://api.github.com/repos/$GITHUB_REPO
# Expect: 200
```

4. If any validation fails: re-prompt the specific failing variable. Retry up to 3 times. On third failure, stop with:
   - Notion token: https://www.notion.so/profile/integrations
   - Slack token: https://api.slack.com/apps
   - GitHub token: https://github.com/settings/tokens

5. Write all values to `harness/.env`:
```bash
cat > harness/.env <<EOF
NOTION_API_KEY=$NOTION_API_KEY
NOTION_DATABASE_ID=$NOTION_DATABASE_ID
NOTION_AGENT_USER_ID=$NOTION_AGENT_USER_ID
SLACK_BOT_TOKEN=$SLACK_BOT_TOKEN
SLACK_CHANNEL_ID=$SLACK_CHANNEL_ID
GITHUB_TOKEN=$GITHUB_TOKEN
GITHUB_REPO=$GITHUB_REPO
EOF
```
6. Print: "Credentials validated and written to harness/.env ✓"
