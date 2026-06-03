# Orchestration Harness

A skill-driven, loop-based orchestrator. Polls Notion/Slack/GitHub, queues Events, dispatches agent Sessions. No daemon — `/loop` is the orchestrator.

## Entry Point

`/loop` → reads `harness/CLAUDE.md` (tick sequence) → runs pollers → dispatcher → subagents.

**When `/loop` fires, run the tick sequence in `harness/CLAUDE.md` directly. Do NOT invoke the `setup` skill — setup is a one-time operation run via `/setup` only.**

## Key Files

| Path | Purpose |
|------|---------|
| `CONTEXT.md` | Domain glossary (Tick, Event, Entity, Session, etc.) |
| `harness/CLAUDE.md` | Tick sequence — L1 routing table |
| `harness/skills/` | Poller and dispatcher skills |
| `harness/db/harness.db` | SQLite state store |
| `harness/.env.example` | Required env vars |

## Domain Vocabulary

Core terms: **Tick**, **Event**, **Entity**, **Session**, **Dispatcher**, **Context Key**, **Tick Lock**, **Blocked**.  
Full definitions: `@CONTEXT.md`

## Skills

- `sync-state.md` — acquire/release tick lock, read/write `last_sync_at`
- `poll-notion.md`, `poll-slack.md`, `poll-github.md` — source pollers
- `dispatch.md` — groups events by context key, spawns subagents
- `entity-registry.md` — entity dedup and link tracking

## Loop Interval

Always schedule the next tick at **270s**. Never change this without asking the user first.

## Rules

- Never kill or overwrite the tick lock without reading `sync-state.md` first.
- Context key is always a Notion ticket entity ID — never a Slack thread or PR.
- Agents cannot create or modify skill files (v1 constraint).
- If any poller fails during a tick: release lock, stop — do not update `last_sync_at`.
- During `/loop` ticks, only invoke skills explicitly listed in `harness/CLAUDE.md`. Never auto-invoke `setup` or any other skill not in the tick sequence.
