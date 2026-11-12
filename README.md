# Discord LLM Connector

**by:buf0rd** · GitHub-ready standalone Discord bot for Ollama / Open WebUI / OpenAI-compatible gateways.

> **Terminology:** this is a **Discord Gateway bot**, not an incoming Discord webhook. A webhook can post to a channel but cannot receive and process arbitrary user messages. This project uses discord.py to listen for commands and reply.

Features: explicit `!ask` and `!search`, Tavily or SearXNG, per-channel/thread context, model selection, access control, cooldowns, and Linux systemd deployment.

```text
Discord chat → discord.py bot → Ollama / Open WebUI (OpenAI-compatible API)
                           ↘ Tavily or SearXNG (!search only)
```

## Repository layout

```text
install.sh                 # Deployment wizard + dependency checks + rollback
src/bot.py                # Discord Gateway client, commands, memory
src/backend.py            # Ollama/Open WebUI/OpenAI-compatible client
src/websearch.py          # Tavily and SearXNG search
src/settings.py           # Config validation
src/configure.py          # Interactive configuration
src/install.py            # Atomic install/rollback helper
systemd/discord-llm.service
tools/patch_bot.py        # Compatibility helper used by unit tests
tests/test_*.py           # Offline HTTP mock tests
config.example.json       # Example only, not populated with credentials
requirements.txt          # Python dependencies
.github/workflows/ci.yml  # Basic CI
```

**Do not commit** `/etc/discord-llm/config.json`, API tokens, service memory databases, or backups. This repo contains no configured secrets. Read [SECURITY.md](SECURITY.md) before deployment.

## Install it

Clone the repository or extract the release ZIP. Run the installer from the repository root; it installs the individual source files, not an embedded script payload. Existing configuration is preserved unless `--reconfigure` is specified.

Ubuntu/Debian, Python 3.10+, and a running systemd host. Run on the model host or a
separate machine that can reach it. Existing Ollama and Open WebUI installations
stay as they are. No virtual-host, Docker, firewall, or model-download changes.

```bash
sudo bash install.sh
```

Fresh installs prompt for credentials and settings. Re-running keeps your existing
config and SQLite history, adds missing defaults, and replaces the connector's
managed source files and systemd unit. To change settings during installation:

```bash
sudo bash install.sh --reconfigure
```

The installer checks dependencies, runs local mock tests, backs up managed files,
installs the connector, and starts/enables the service. Existing valid Python
packages are reused. Fresh installs include discord.py's voice dependencies to
avoid missing-library warnings; the connector itself provides text chat only.
Dependency constraints are discord.py[voice]>=2.4,<3 and aiohttp>=3.10,<4; this is
not a locked dependency build. Installed versions are recorded under /opt/discord-llm.

## Add the bot to Discord. Logging in is not the same thing.

1. Open https://discord.com/developers/applications and create/select your application.
2. On the Bot page, obtain the BOT token and enable Message Content Intent.
3. On OAuth2 > URL Generator, choose the bot scope and server installation where offered.
4. Grant View Channels, Send Messages, Send Messages in Threads, Read Message History,
   and Attach Files. Open the generated URL and authorize the bot in your server.
5. If the channel is private, add the bot and grant the same channel permissions.
6. In your Discord user settings, enable Advanced > Developer Mode. Right-click the
   intended channel and Copy Channel ID. Use the channel ID, not the server ID.

The service logs its bot ID after connecting. It also reports configured channels
it cannot see and missing channel permissions. Private threads require membership;
archived/locked threads can still prevent delivery. The startup check cannot predict
every Discord permission or thread-state change.

## Pick the backend

| backend | base_url example | Backend API key |
|---|---|---|
| ollama | http://127.0.0.1:11434 | Normally blank for direct local Ollama |
| openwebui | http://openwebui.example.lan:3000 | Open WebUI user's API key |
| openai | http://gateway.lan:8000 | Whatever that gateway requires |

Enter the origin/prefix before /api or /v1. The connector appends /v1/models and
/v1/chat/completions for Ollama/OpenAI-compatible services; /api/models and
/api/chat/completions for Open WebUI. Both model listing and nonstreaming text
completions must be supported. localhost means the machine running this connector.

The Discord token and backend API key are different credentials. Setup hides their
input. When changing backend type, the wizard clears the old backend key by default
so it does not get forwarded to a different service. The same-backend URL change
keeps its key unless you explicitly clear it with a single dash.

For Open WebUI, enable API Keys globally, then grant API Keys to the account's group.
Some older versions require that group permission even for admins. Generate the key
under your personal Settings > Account. It inherits that account's model access.
If endpoint restrictions are enabled, permit /api/models and /api/chat/completions.
Disable any forced streaming setting for the selected model; this bridge consumes
nonstreaming text responses. It does not implement Open WebUI's native tool loop,
MCP execution, RAG request fields, or saved-chat synchronization.

Leave model blank to pick the first returned model ID alphabetically on the first
question. Pick an exact installed chat-model ID when possible; alphabetical discovery
cannot distinguish embedding models from chat models. No models are downloaded.

## Commands

| Command | What it does |
|---|---|
| @Bot your question | Ask the selected model |
| !ask your question | Same thing without a mention |
| !search your question | Search your selected provider and summarize the snippets with result links |
| !models | List backend model IDs |
| !model | Show this conversation's model |
| !model exact-id | Admin: switch this conversation's model and clear its memory |
| !reset | Admin: clear this conversation's memory |
| !status | Check model-list connectivity; show backend, memory, and search configuration |
| !help | Show commands |

Wait five seconds between commands by default. Rapid repeats are ignored. One request
runs at a time by default; busy requests receive a retry message instead of joining
an unbounded queue. !status checks the model-list endpoint, not generation or the search provider.

## Access and memory

At least one channel ID is required. An allowed parent channel also allows its threads.
An empty user_ids list permits everyone who can use those channels. Otherwise only
listed users qualify. Configured admin_ids and members with Manage Server permission
can change/reset models; both still obey the channel/user allowlists. DMs and bots
are ignored. Generated replies cannot ping users or roles.

Each channel/thread has separate shared memory. Only submitted questions and bot
answers enter it; ambient chat is not collected. SQLite retains up to 10 turns and
24,000 content characters per conversation. These are character limits, not token
limits. Use a model/context window that fits or lower the limits in bot.py. Idle
conversations expire after seven days, with cleanup on startup and writes. That is
logical deletion, not secure erasure. Backend type and URL scope the stored memory.
Switching back to an old endpoint may resume its unexpired history. !reset clears it.

## !search is optional

Leave searxng_url blank during setup and finish SearXNG later. Normal chat still works.
To enable it later, set your actual endpoint, for example:

```json
"searxng_url": "https://search.example.org/search"
```

For SearXNG, the helper adds q and format=json. It also accepts the Open WebUI-style q=<query>
template, replacing its query safely. Static parameters such as language=en or
time_range=day are retained. JSON output must be enabled on SearXNG:

```yaml
search:
  formats:
    - html
    - json
```

Merge this into the existing search section, preserving other settings. SearXNG
engine suspensions are not a model/Discord problem. The connector reports upstream
errors when SearXNG returns no usable results. No server settings are changed here.

Each !search sends the explicit query to the selected provider, passes up to five usable snippets
to the selected backend, and appends actual result URLs. It works with either Ollama
or Open WebUI as the text backend. It does not invoke Open WebUI's web-search feature.
It does not fetch full result pages, execute tools, or save search evidence to shared
conversation memory. Searches are independent; include the complete question each time.

The search prompt treats external content as untrusted evidence, but prompt-injection
resistance and citation correctness are not guaranteed. The app's source list comes
from search results; the model's inline citation choices are not independently checked.
If generation fails after a successful search, result links are still returned.
Long replies and source lists arrive as response.txt attachments.

Search query limit: 1,000 characters. Normal question limit: 8,000 characters.
search_result_count defaults to 5 (1–10); search_timeout_seconds defaults to 30 (5–120).
TLS verification stays enabled. Redirects are rejected with an actionable error.
This connector does not inherit HTTP_PROXY/HTTPS_PROXY or configure SearXNG auth.
Use a reachable JSON endpoint; search queries also go to its upstream engines.

## Change settings

```bash
sudo /opt/discord-llm/venv/bin/python /opt/discord-llm/configure.py
sudo systemctl restart discord-llm
```

Enter keeps a value; a single - clears an optional value. Required token/channel fields
cannot be empty. The wizard validates before writing and uses an atomic replacement.
It preserves unknown JSON keys and advanced settings. Or edit directly:

```bash
sudoedit /etc/discord-llm/config.json
sudo systemctl restart discord-llm
```

Advanced keys: timeout_seconds=180, max_tokens=2048, cooldown_seconds=5,
max_concurrent=1, search_result_count=5, search_timeout_seconds=30, system_prompt.
The setup preserves your existing system_prompt; fresh installs use direct, factual
instructions. !search uses a separate evidence-focused prompt.

## Operations

```bash
sudo systemctl status discord-llm --no-pager
sudo journalctl -u discord-llm -n 80 --no-pager
sudo journalctl -u discord-llm -f
sudo systemctl restart discord-llm
```

Code: /opt/discord-llm. Config: /etc/discord-llm/config.json, root:discord-llm mode 640.
State: /var/lib/discord-llm/memory.sqlite3, service-owned private directory.
Service: discord-llm, dedicated unprivileged account, automatically started at boot.
App logs omit prompts, answers, and tokens. Backend providers may log their own requests.

HTTP 401/403 from Open WebUI means check its key, account/group permissions, and endpoint
restrictions. HTTP 404 means check the endpoint/model ID. Discord login success followed
by silence means check invite, channel access, IDs, Message Content Intent, and cooldown.
The installer passing tests is not proof those external settings are correct.

## Rollback and removal

Each installation prints a rollback command for its root-only backup under
/var/backups/discord-llm. It restores managed code, the config snapshot, the unit,
and prior enabled/running state. It does not revert Python packages or database history.
Use it only when you want to restore that config snapshot too. Fresh-install rollback
leaves the service account, venv, empty directories, and any newly created state in place.

To uninstall service/code while keeping configuration and history:

```bash
sudo systemctl disable --now discord-llm
sudo rm -f /etc/systemd/system/discord-llm.service
sudo systemctl daemon-reload
sudo rm -rf /opt/discord-llm
```

Remove /etc/discord-llm and /var/lib/discord-llm separately only if you want to delete
credentials and conversation history. Backups also contain config snapshots.

## References

- https://docs.ollama.com/api/openai-compatibility
- https://docs.openwebui.com/reference/api-endpoints/
- https://docs.openwebui.com/features/authentication-access/api-keys/
- https://discordpy.readthedocs.io/en/latest/intents.html
- https://docs.searxng.org/dev/search_api.html


## Run the offline tests

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# --test-only prefers /opt/discord-llm/venv if present; otherwise system Python.
# For isolated local testing, activate .venv first and run:
. .venv/bin/activate
bash install.sh --test-only
```

No Discord login or external search requests are performed. On existing hosts, `--test-only` uses the service venv if present. The CI workflow runs tests in its own clean runner.

## Tavily search

Choose `tavily` during setup, then enter a Tavily API key from https://app.tavily.com/.
For an existing install, run `sudo bash install.sh --reconfigure` to change the provider and API key.
Config keys: `search_provider: "tavily"` and `tavily_api_key: "YOUR_KEY"`.
Keep the model backend `api_key` separate. Restart `discord-llm` after manual edits.
`!search <question>` sends the query to Tavily and gives the returned snippets to your selected model.
Basic search is explicit; automatic depth selection, Tavily answers, images and raw pages are disabled.
Requests consume Tavily account usage. No automatic fallback to SearXNG.
Switch back with `search_provider: "searxng"`; the saved SearXNG URL is retained.
Official API: https://docs.tavily.com/documentation/api-reference/endpoint/search

## License

MIT License — Copyright (c) 2026 buf0rd. See [LICENSE](LICENSE) for the full license text.
