# by:buf0rd | Discord LLM Connector
# Keep the setup direct. Keep credentials out of the logs.
"""Guarded patch: preserve existing local bot customizations outside these anchors."""
def patch_bot(text):
    marker = '# discord-llm explicit-search v1'
    if marker in text:
        if 'from websearch import answer_search' not in text or "if command == '!search':" not in text:
            raise ValueError('Incomplete prior search patch; restore the previous bot.py first.')
        return text
    pairs = [
        ('from backend import Backend, BackendError',
         'from backend import Backend, BackendError\nfrom websearch import answer_search\n' + marker),
        ('!models — available models', '!search <question> — search the web and summarize snippets with source links\n!models — available models'),
        ("commands = {'!ask', '!models', '!model', '!reset', '!status', '!help'}",
         "commands = {'!ask', '!search', '!models', '!model', '!reset', '!status', '!help'}"),
        ("        if not arg:\n            return await self.send_text(message, HELP)",
         "        if command == '!search':\n            return await answer_search(self, message, model, arg)\n        if not arg:\n            return await self.send_text(message, HELP)"),
    ]
    for old, new in pairs:
        if text.count(old) != 1:
            raise ValueError('Installed bot.py differs from the supported bridge; no changes made. Provide bot.py (not config.json) for a tailored update.')
        text = text.replace(old, new, 1)
    compile(text, 'bot.py', 'exec')
    return text

