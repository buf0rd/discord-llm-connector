# Security and deployment

This project requires a Discord bot token. Never publish that token, Tavily keys, or Open WebUI keys. The default installer stores credentials in `/etc/discord-llm/config.json` (root:discord-llm, `0640`) and runs under a dedicated restricted account.

- For a public GitHub repository, publish **only source files**. Do not copy in `/etc/discord-llm`, `/var/lib/discord-llm` or `/var/backups/discord-llm`.
- If a token appears in a commit, revoke or rotate it immediately; deleting the file from the latest commit is not sufficient because Git history retains it.
- Restrict the bot to explicit Discord channel IDs and, if needed, user IDs. Grant only required channel permissions and enable Message Content Intent.
- The model backend URL must be trusted. A backend API key is sent to the configured backend. Avoid exposing Ollama directly to the public Internet. Use HTTPS for remote endpoints.
- Treat prompts and Tavily/SearXNG results as untrusted data. Search results may attempt prompt injection; this bot does not execute tools or shell commands.
- Review the data-retention policy: questions and responses are persisted locally in `/var/lib/discord-llm/memory.sqlite3`, up to seven days of idle history.
- External search may send question text to Tavily/SearXNG and their upstream services.
- Model backends can log the prompts they process. This bot intentionally avoids logging prompts, answers and tokens, but host logging must still be considered.

If you discover a vulnerability, contact the repository maintainer privately rather than posting secrets in a public issue.
