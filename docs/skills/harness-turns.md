---
name: harness-turns
description: Publish each coding turn to the task's Turn Ledger so a new ChatGPT chat can resume where the last one stopped. Use whenever a task will outlive one conversation.
---

# Harness turns

A ChatGPT chat gets slow long before a task is finished. The Turn Ledger is how
the work survives the chat: publish each turn, then start a fresh chat and call
`resume_task`.

## What this is, and what it is not

The harness never sees the conversation. MCP carries tool calls, not prose, so
the only text on disk is the text you hand over. That makes this a **ledger of
turns you published**, not a transcript:

- It cannot satisfy an acceptance criterion or spend a credit. Ever.
- A turn that called no harness tool leaves **no trace**. Discussion with no
  tool use is genuinely lost. Do not tell the operator otherwise.
- The server writes the list of tool calls it actually observed next to your
  account of the turn. Claiming work that is not in that list is visible.

Receipts and credits remain server-observed. This is model-published. Keep the
two apart when you describe them.

## Protocol

1. Work normally — read, edit, run, open and complete cycles.
2. Before you hand the turn back to the operator, call `publish_turn` with:
   - `user_request` — what they asked, in their words, as faithfully as you can.
   - `assistant_response` — the answer you are about to give them. Write it in
     full; a summary of your own answer is what a future chat will have to
     resume from.
   - `decisions` — choices a later reader could not re-derive from the diff.
   - `next_action` — the single thing that should happen next. `resume_task`
     surfaces this as "Pick up here".
3. If `publish_turn` cannot succeed, call `discard_turn` with a reason. The gap
   is recorded rather than hidden.

## When the harness refuses

- `[TURN_UNPUBLISHED]` on `begin_cycle` — a completed cycle is still
  unpublished. A closed cycle is the only turn boundary the server can prove,
  so this is where "more work without publishing" gets stopped.
- `[TURN_UNPUBLISHED]` on `finish_task` — any unpublished work blocks
  completion. A task is not done while its last stretch of work is unrecorded.
- `[NO_OPEN_TURN]` on `publish_turn` — the server observed no tool calls since
  the last publish. There is nothing to publish; do not invent a turn.

## Resuming

In a new chat, call `resume_task(task_id)` first. It returns the contract, the
gates, the recent published turns, and the pending `next_action`. Read the
ledger before re-reading the code — it tells you what was already ruled out.
