# MyRuflo

A standalone, multi-agent AI tool that talks directly to AI platform APIs — no Claude Code, no Node, no external harness required. It's a from-scratch Python rewrite inspired by [ruflo](https://github.com/ruvnet/claude-flow)'s agent/swarm/memory ideas, built to run as its own independent project.

## What it does

Give it a task in plain English and it decides how to handle it:

- **Simple tasks** run through a single generalist agent.
- **Complex tasks** (bug fixes, features, refactors, security reviews, ...) get routed through a pipeline of specialist agents — `researcher -> planner -> coder -> tester -> reviewer` — each handing its findings to the next.
- **Multi-platform routing**: each step is sent to the best AI platform for the job. A fast, cheap model classifies the task (type + complexity), then a routing table picks among every platform you've configured — Anthropic (Claude), OpenAI (GPT), Google Gemini, xAI (Grok), DeepSeek, and Mistral. Missing API keys narrow the choice gracefully; with only `ANTHROPIC_API_KEY` set, everything runs on Claude exactly as before.

Every agent can read/write files, search the workspace (glob/grep), optionally run shell commands, and read/write a persistent memory store. A lightweight hooks system logs every task and turns successful outcomes into "lessons learned" that get surfaced automatically the next time a similar task comes in — a simplified stand-in for ruflo's self-learning loop.

## Architecture

```
myruflo/
  cli.py              CLI entry point (run / memory / init / doctor / serve)
  config.py           .env-based configuration, 3-tier model routing,
                       per-platform API keys and model overrides
  llm/client.py       Anthropic SDK wrapper (tool-use loop plumbing)
  llm/specs.py        Static specs for every supported AI platform
  llm/providers.py    OpenAI-compatible adapter (httpx) covering OpenAI,
                       Gemini, xAI, DeepSeek, Mistral behind the same call()
  llm/router.py       LLM classifier + rules router: picks the best
                       configured platform per task type and model tier
  tools/              read_file, write_file, edit_file, list_dir, glob_search,
                       grep_search, run_shell — all sandboxed to MYRUFLO_WORKSPACE
  agents/
    roles.py          System prompts for each specialist role
    agent.py          Single-agent tool-use execution loop
  swarm/orchestrator.py  Routes a task to one agent or a multi-agent pipeline
  memory/
    embedding.py      Dependency-light hashing-trick text embeddings (numpy only)
    store.py          SQLite-backed vector store (add/search per namespace)
  hooks/manager.py    Pre/post-task logging + pattern distillation into memory
  web/                FastAPI app for `myruflo serve`: auth, chat, admin panel,
                       tool-availability toggles, its own SQLite DB (data/app.db)
```

Design choices worth knowing about:

- **No Claude Code dependency.** Agents call platform APIs directly with `tools=[...]` (function calling), execute the requested tool locally, and feed the result back — a self-contained loop.
- **One internal dialect, many platforms.** Agents always speak Anthropic-style content blocks; `llm/providers.py` translates to/from the OpenAI chat-completions dialect for every other platform (they all expose OpenAI-compatible endpoints), so the tool-use loop is identical everywhere and needs no per-provider code.
- **Routing degrades gracefully.** `MYRUFLO_ROUTER=auto` uses an LLM classifier with a keyword-rules fallback; `rules` skips the LLM call; `off` pins everything to `MYRUFLO_DEFAULT_PROVIDER`. Only platforms with configured keys are ever considered.
- **Memory uses hashed bag-of-words vectors, not a real embedding model**, so the whole project only needs `anthropic` + `numpy` to install. It's good enough for "have I seen something like this before" recall; swap `memory/embedding.py` for a real embedding API/model if you need stronger semantic search.
- **The shell tool is off by default** (`MYRUFLO_ALLOW_SHELL=false`). Turning it on lets agents run arbitrary commands in the workspace — only do this in a workspace/machine you're comfortable letting an LLM act on. There's a small denylist for obviously catastrophic commands, but it is a guardrail, not a sandbox.
- **File tools are sandboxed** to `MYRUFLO_WORKSPACE` — paths that resolve outside it are rejected.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate        # or: source .venv/bin/activate on macOS/Linux
pip install -e .

myruflo init                  # creates .env and workspace/, data/ folders
# edit .env and set ANTHROPIC_API_KEY
myruflo doctor                # sanity-check config + dependencies
```

## Usage

```bash
# Auto-routed: simple question -> single agent, complex ask -> swarm pipeline
myruflo run "explain what this workspace's main.py does"

# Force the full researcher -> planner -> coder -> tester -> reviewer pipeline
myruflo run --swarm "add input validation to the signup endpoint"

# Force a single generalist agent regardless of task complexity
myruflo run --no-swarm "fix the off-by-one error in paginate()"

# Inspect what the tool has learned / remembered
myruflo memory list
myruflo memory search "pagination bug" --namespace patterns
```

All file operations happen inside `./workspace` by default (change with `MYRUFLO_WORKSPACE` in `.env`) — point it at a real project directory to have MyRuflo work on it.

## Web UI

`myruflo serve` runs a local web UI on top of the same agents/orchestrator/memory code the CLI uses — a dark-blue (with a light mode) chat interface, multi-user accounts, and a role-gated admin panel.

```bash
myruflo serve
# open http://localhost:8080
```

- **Accounts**: the first person to register becomes the admin; everyone after that is a regular user. Each user has their own private conversation history.
- **Chat**: pick Auto-detect / Force single agent / Force full swarm per message, same routing as `myruflo run`'s `--swarm`/`--no-swarm` flags. The composer stays pinned at the bottom of the screen while the conversation scrolls independently above it.
- **File attachments**: attach up to 5 files (5MB each) to a message. Images are sent to Claude as native vision content; other text-decodable files (code, `.txt`, `.json`, `.md`, ...) are inlined into the prompt; binary formats that can't be read as text are stored and noted but not parsed. Files live under `<workspace>/uploads/<conversation_id>/`, and attachment metadata is tracked in `data/app.db`'s `attachments` table.
- **Enhance**: the ✨ button next to the composer sends your draft to a quick, tool-free LLM call (fast model tier) that rewrites it to be clearer and more specific, then drops the result back into the textarea for you to edit or send.
- **Live status**: while a message is running, a single status line under the composer reflects what's actually happening in the background — which pipeline stage is active (`Researching...`, `Writing code...`, etc.) and which tool is currently in use (`Using write_file...`) — driven by `conversations.status` in `data/app.db`, polled every ~1.2s.
- **Generated files**: any file the agent writes or edits via its `write_file`/`edit_file` tools during a run is surfaced as a downloadable chip on the assistant's reply, sourced straight from the workspace.
- **Memory**: a read-only `/memory` page mirrors `myruflo memory list`/`search`.
- **Admin panel** (`/admin`, visible only to admins): usage dashboard (users, conversations, task volume, success rate, recent activity) and a page to enable/disable which agent tools (`read_file`, `write_file`, `edit_file`, `list_dir`, `glob_search`, `grep_search`, `run_shell`) are available to every user. `run_shell` still requires `MYRUFLO_ALLOW_SHELL=true` regardless of that toggle — the env var is the hard kill switch, the admin toggle can only further restrict it.
- Set `WEB_SECRET_KEY` in `.env` (see `.env.example`) so login sessions survive a restart; without it a random key is generated each time the server starts.
- Web UI accounts/conversations/stats live in `data/app.db`, separate from the agent's own `data/memory.db`.

## Hosting on GCP

The Anthropic API key lives in Secret Manager as **`ANTHROPIC_AI_KEY`**, not in a committed `.env`. `myruflo/config.py` resolves the key in this order:

1. **`ANTHROPIC_API_KEY` env var** — set locally via `.env`, or injected by Cloud Run's `--set-secrets=ANTHROPIC_API_KEY=ANTHROPIC_AI_KEY:latest` binding. This is what the `myruflo-job` Job uses; no extra dependency needed for this path.
2. **`MYRUFLO_EVL` env var** — historical fallback name, kept for compatibility with any deployment still binding the key under that name.
3. **`ANTHROPIC_AI_KEY` env var** — the name currently used on the `myruflo` web Service's secret binding (`--set-secrets=ANTHROPIC_AI_KEY=ANTHROPIC_AI_KEY:latest`).
4. **Direct Secret Manager read** — fallback for hosting setups that don't bind the secret as an env var at all. Only attempted when a GCP project is inferable (`GOOGLE_CLOUD_PROJECT`, which Cloud Run/GCE set automatically, or `MYRUFLO_GCP_PROJECT`) and the optional `google-cloud-secret-manager` package is installed (`pip install -e ".[gcp]"`).

Run `myruflo doctor` to see which source supplied the key (`source: env`, `source: env:MYRUFLO_EVL`, `source: env:ANTHROPIC_AI_KEY`, or `source: secret-manager`).

### Multi-platform keys from Secret Manager

Every other platform's key can live in Secret Manager too — no env var bindings needed. Whenever a GCP project is inferable (`GOOGLE_CLOUD_PROJECT` on Cloud Run/GCE, or `MYRUFLO_GCP_PROJECT` locally) and a key isn't found in the environment, the app looks up these default secret IDs:

| Platform | Default secret ID(s) | Override with |
|---|---|---|
| Anthropic | `ANTHROPIC_AI_KEY`, `ANTHROPIC_API_KEY` | `MYRUFLO_SECRET_NAME` |
| OpenAI | `OPENAI_API_KEY` | `MYRUFLO_SECRET_OPENAI` |
| Gemini | `GEMINI_API_KEY`, `GOOGLE_API_KEY` | `MYRUFLO_SECRET_GEMINI` |
| xAI | `XAI_API_KEY`, `GROK_API_KEY` | `MYRUFLO_SECRET_XAI` |
| DeepSeek | `DEEPSEEK_API_KEY` | `MYRUFLO_SECRET_DEEPSEEK` |
| Mistral | `MISTRAL_API_KEY` | `MYRUFLO_SECRET_MISTRAL` |

Create a secret per platform you want enabled (e.g. `gcloud secrets create OPENAI_API_KEY --data-file=-`), and `deploy/gcp/deploy.sh` grants the runner service account access to whichever of these secrets exist. Platforms without a secret are simply skipped by the router. The container image installs `google-cloud-secret-manager`, so this works on Cloud Run with zero extra configuration.

### One image, two Cloud Run shapes

The same container backs both a **Cloud Run Job** (`myruflo-job`, a "run a task, print the result, exit" batch runner) and a **Cloud Run Service** (`myruflo`, the web UI). `docker/entrypoint.sh` picks the mode at startup: if `MYRUFLO_TASK` is set it runs that one-shot CLI task and exits (the Job's behavior — reading the task from an env var rather than a CLI arg specifically so job executions can pass arbitrary free-form text without hitting gcloud's comma-separated `--args` escaping rules); otherwise it runs `myruflo serve`, which listens on `$PORT` for the Service.

The web Service is pinned to `--max-instances=1 --min-instances=1`: its SQLite data (`data/app.db`, `data/memory.db`) lives on local disk, and a single always-on instance keeps it consistent while running.

**Cloud persistence (logins, accounts, conversations, memory)**: the image ships [Litestream](https://litestream.io), which continuously replicates `app.db` (users/logins/conversations/settings) and `memory.db` (agent memory) to a GCS bucket and restores them at startup. `deploy.sh` creates the bucket (`<project>-myruflo-data`), grants the runner access, and sets `LITESTREAM_BUCKET` on both the Service and the Job — so accounts survive redeploys, crashes, and cold starts with no further setup. Unset `LITESTREAM_BUCKET` to disable. (`workspace/` files and `hooks.jsonl` stay ephemeral; mount a GCS volume if you need those too.)

### Deploy

Requires the `gcloud` CLI, a GCP project with billing enabled, and the `ANTHROPIC_AI_KEY` secret already created in Secret Manager (this script only grants access to it — it never touches the plaintext key).

```bash
deploy/gcp/deploy.sh YOUR_PROJECT_ID [REGION] [SECRET_NAME]
# e.g. deploy/gcp/deploy.sh myruflo us-central1 ANTHROPIC_AI_KEY
```

This builds the image via Cloud Build, pushes it to Artifact Registry, creates a dedicated `myruflo-runner` service account with `roles/secretmanager.secretAccessor` on the secret, and deploys both the `myruflo-job` Cloud Run Job and the `myruflo` Cloud Run Service (the web UI, publicly reachable — `--allow-unauthenticated` — since the app has its own login/admin-role access control).

### Run a task

```bash
gcloud run jobs execute myruflo-job --region=us-central1 \
  --update-env-vars="MYRUFLO_TASK=explain what this workspace does"
```

Each execution starts from a clean container — `/workspace` and `/data` (memory + hooks log) reset every run, since there's no disk by default. To persist memory/workspace across executions, mount a GCS bucket as a volume:

```bash
gcloud run jobs update myruflo-job --region=us-central1 \
  --add-volume=name=data,type=cloud-storage,bucket=YOUR_BUCKET \
  --add-volume-mount=volume=data,mount-path=/data
```

### Local Docker test (no GCP needed)

```bash
docker build -t myruflo .
docker run --rm -e ANTHROPIC_API_KEY=sk-ant-... -e MYRUFLO_TASK="summarize this workspace" myruflo
```

## Testing

```bash
pip install pytest
pytest -q
```

Tests cover memory search, hooks/pattern recall, file-tool sandboxing, swarm routing logic, the multi-platform router (classification, preference order, graceful degradation), and the OpenAI-compat dialect translation including a full simulated tool-use round trip — none of them call any AI platform API, so they run offline.

## Extending

- **New role**: add a `(model_tier, system_prompt)` entry to `ROLES` in `myruflo/agents/roles.py`, then reference it from `swarm/orchestrator.py`'s routing table.
- **New tool**: add a JSON-schema entry in `tools/schemas.py`, implement it in `tools/file_ops.py` or a new module, and wire it into `tools/registry.execute_tool`.
- **Stronger memory**: replace `memory/embedding.py`'s `embed()` with a call to a real embedding model/API — `memory/store.py` only depends on `embed()` returning a fixed-size numpy vector.
