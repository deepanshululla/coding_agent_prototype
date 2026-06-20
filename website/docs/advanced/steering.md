---
sidebar_position: 1
title: Steering Messages
description: Injecting user input mid-run to redirect the agent while it's still executing — what it requires and why v1 skips it.
---

# Steering Messages

:::tip Verify
Complete a task, then inject a follow-up via the steering API and confirm the agent continues from where it left off **without replaying prior tool calls**.
:::

A steering message is a user-provided input that arrives while the agent is still running — not as a new task after it finishes, but as a course-correction mid-loop. Think of it as tapping the agent on the shoulder: "actually, stop looking at that file and check this one instead."

Pi (the reference implementation this project is modelled on) implements this via a `getSteeringMessages()` hook called inside the inner loop's condition check. This project has the skeleton for it in `run_agent` — the `pending_messages` list — but the async input handling needed to populate it at runtime is skipped in v1.

:::note
Steering messages are a **partial/planned feature** in v1. The `pending_messages` list exists in the agent loop code, and the inner loop checks it. What's missing is the mechanism to push messages into it from outside the loop while it's running. This page explains the design so you can add it.
:::

## How the outer loop supports it

`run_agent` has two loops:

```
OUTER LOOP  ←  re-enters if pending_messages were queued after the inner loop stops
  INNER LOOP  ←  the tool-call cycle; checks pending_messages each iteration
```

The inner loop condition is:

```python
while (has_more_tool_calls or pending_messages) and iteration < MAX_ITERATIONS:
```

At the top of each iteration, pending messages are flushed into the main history:

```python
if pending_messages:
    messages.extend(pending_messages)
    pending_messages.clear()
```

And at the bottom of `run_agent`, v1 just breaks out of the outer loop unconditionally:

```python
break  # no follow-up support in v1
```

Replace that `break` with a check — "are there new messages in `pending_messages`?" — and the outer loop becomes a real steering channel.

## Why it's non-trivial

The problem is getting input *into* `pending_messages` from outside while the `async for chunk in stream_response(...)` loop is blocking the event loop iteration.

Three approaches, each with tradeoffs:

### Option A — asyncio.Queue + background input reader

```python
steering_queue: asyncio.Queue[str] = asyncio.Queue()

async def read_stdin_loop():
    """Runs concurrently; puts lines from stdin into the queue."""
    loop = asyncio.get_event_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if line:
            await steering_queue.put(line.strip())

async def run_agent(task: str) -> None:
    asyncio.create_task(read_stdin_loop())
    ...
    # At the top of each inner-loop iteration:
    while not steering_queue.empty():
        msg = await steering_queue.get()
        pending_messages.append({"role": "user", "content": msg})
```

This works but has a race: if the agent finishes before the user types anything, `read_stdin_loop` keeps running and holds the process open. You need cancellation logic.

### Option B — check between tool calls only

Instead of checking mid-stream, only check `pending_messages` between tool call batches — at the top of each inner-loop iteration, which is already where the current code flushes them. The user can type a steering message during tool execution (which can take seconds) and it'll be seen at the next iteration boundary.

This is simpler than concurrent stdin reading, but the agent won't be redirected mid-stream if it's producing a long text response with no tool calls.

### Option C — external signal (API / queue)

For an [RPC mode](../programmatic-usage/rpc-mode.md) deployment, steering messages arrive over the same channel as the original task — a WebSocket, a message queue, or a `PATCH /run/{id}` endpoint. The RPC layer pushes them into `pending_messages` from outside the event loop.

This is the cleanest architecture for programmatic use but requires the HTTP server wrapper described in [RPC Mode](../programmatic-usage/rpc-mode.md).

## Pi's `getSteeringMessages` pattern

In pi's TypeScript agent core, the inner loop calls `getSteeringMessages()` — an injected async function — at the top of each iteration. The caller supplies this function; typically it checks a channel or queue for messages that arrived from the terminal UI while the agent was streaming.

```typescript
// pi's pattern (TypeScript — for reference)
while (hasMoreToolCalls || pendingMessages.length > 0) {
  const steering = await getSteeringMessages();
  if (steering.length > 0) {
    messages.push(...steering);
  }
  // ... rest of inner loop
}
```

The Python equivalent would be an `async def get_steering_messages() -> list[dict]` parameter to `run_agent`:

```python
async def run_agent(
    task: str,
    get_steering_messages=None,   # callable: async () -> list[dict]
) -> None:
    ...
    while (has_more_tool_calls or pending_messages) and iteration < MAX_ITERATIONS:
        if get_steering_messages:
            new_msgs = await get_steering_messages()
            pending_messages.extend(new_msgs)
        ...
```

The caller provides any implementation they want — stdin reader, queue consumer, no-op.

## What the inner loop checks today

Even in v1, the inner loop condition already handles `pending_messages`:

```python
while (has_more_tool_calls or pending_messages) and iteration < MAX_ITERATIONS:
    iteration += 1

    if pending_messages:
        messages.extend(pending_messages)
        pending_messages.clear()
```

If you populate `pending_messages` before calling `run_agent`, those messages will be included at the first iteration. This means you can inject a "system note" or context prefix programmatically today, even without the async input reader. What you can't do yet is inject messages *while the loop is running*.

## Safety considerations

- **MAX_ITERATIONS** still applies. Steering messages count as new iterations. A user who keeps steering could hit the 30-iteration cap.
- **Message history grows** with each steering turn. If you add many steering messages across a long session, watch the [context window](../concepts/context-window.md) — compaction may become necessary sooner.
- **Tool calls in flight.** If the agent is mid-batch when a steering message arrives, the batch will complete before the message is processed (assuming Option B above). Don't assume steering is instantaneous.

## Related pages

- [The Agent Loop](../architecture/the-agent-loop.md) — outer/inner loop structure
- [Context Compaction](./compaction.md) — managing history size across long steered sessions
- [RPC Mode](../programmatic-usage/rpc-mode.md) — external message delivery via HTTP
