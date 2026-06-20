---
sidebar_position: 2
title: Containerization
description: How to run the coding agent inside a Docker container to limit filesystem blast radius, isolate the process, and control network egress.
---

# Containerization

Running the agent directly on your host machine means it can read, write, and execute anywhere your user account can reach. Containerizing it limits that surface to exactly what you choose to mount. This is the most effective operational control available.

:::note
Containerization is a recommended operational practice, not something the agent handles automatically. The project does not ship a `Dockerfile` or `docker-compose.yml` — this page describes how to set one up.
:::

## Why it matters

The agent runs `bash` with `shell=True`. An instruction like "clean up temp files" could spiral into `rm -rf` calls the LLM deemed reasonable. A `write_file` call with an absolute path can overwrite anything the process can reach.

Inside a container:

- The filesystem is isolated to the container image plus any explicit mounts.
- A `rm -rf /` inside the container destroys the container, not your host.
- You can mount a single project directory read-write and keep everything else read-only or absent.
- Network egress can be restricted to only the LLM provider's API endpoint.

## A minimal Dockerfile

```dockerfile
FROM python:3.14-slim

# Install uv for fast dependency management
RUN pip install uv

# Set working directory for the agent source
WORKDIR /agent

# Copy only what the agent needs to run
COPY pyproject.toml .
COPY src/ ./src/
COPY main.py .

# Install dependencies declared in pyproject.toml
RUN uv sync

# Default entrypoint — override with your task at docker run time
ENTRYPOINT ["uv", "run", "main.py"]
```

Build it:

```bash
docker build -t coding-agent .
```

## Running the agent on a project

Mount your project directory at `/workspace` inside the container. The agent will anchor its working directory to wherever you point it via the system prompt.

```bash
docker run --rm \
  -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  -v "$(pwd)/my-project:/workspace" \
  -w /workspace \
  coding-agent "add type hints to all functions in tools.py"
```

Key flags:

| Flag | Purpose |
|---|---|
| `--rm` | Destroy the container when the task finishes — no residue |
| `-e ANTHROPIC_API_KEY` | Inject only the API key the agent needs; nothing else from your host env |
| `-v "$(pwd)/my-project:/workspace"` | Mount the target project read-write; the rest of your filesystem is absent |
| `-w /workspace` | Set the container working directory so `os.getcwd()` returns `/workspace` |

:::tip
If you only need the agent to read from a directory (for analysis tasks), add `:ro` to the mount flag: `-v "$(pwd)/my-project:/workspace:ro"`. The agent will still be able to run `bash` commands but `write_file` and `edit_file` will fail on permission errors, giving you a hard stop.
:::

## Trade-offs

### What containerization protects

- **Filesystem blast radius.** The agent can only modify files under the mounted path. A rogue `rm -rf /` inside the container removes the container's own root, not your host.
- **Host environment variables.** Unless you explicitly pass them with `-e`, none of your host environment is visible inside the container. Your SSH keys, other API keys, and shell config are absent.
- **Lateral movement.** The container has no access to other projects, home directories, or system config files.

### What containerization does not protect

- **The mounted directory itself.** Everything under the mount is as writable as on your host. If the agent misbehaves, it can still overwrite or delete files in the project you mounted. Use a git repository and review `git diff` after any session.
- **Network egress.** By default, Docker containers can reach the internet. The agent can `curl` arbitrary endpoints. To restrict this, use Docker's `--network` flag or a network policy:

```bash
# Allow only the Anthropic API (approximate — adjust for your provider)
docker run --rm \
  --network=host \
  --add-host=api.anthropic.com:$(dig +short api.anthropic.com | head -1) \
  -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  -v "$(pwd)/my-project:/workspace" \
  -w /workspace \
  coding-agent "your task here"
```

For stricter control, use a custom Docker network with `--internal` and route only the provider endpoint through a proxy.

- **Resource exhaustion.** A looping agent can still consume CPU and memory. Set container resource limits:

```bash
docker run --rm \
  --memory=512m \
  --cpus=1.0 \
  -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  -v "$(pwd)/my-project:/workspace" \
  -w /workspace \
  coding-agent "your task here"
```

## Security considerations

Containerization complements, but does not replace, the controls described in [Security Model](./security.md). In particular:

- The agent can still be manipulated by prompt injection via files it reads inside the mount.
- The API key is visible inside the container via `echo $ANTHROPIC_API_KEY`. Keep your key scoped and rotate it regularly.
- Review the agent's output and run `git diff` before committing anything the agent produced.

See [Security Model](./security.md) for the full threat model and [Permissions & Gating](./permissions.md) for adding a human-in-the-loop confirmation step before destructive tool calls.
