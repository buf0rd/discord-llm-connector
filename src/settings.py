# by:buf0rd | Discord LLM Connector
# Catch bad config here. Don't wait for somebody to ask the bot a question.
from urllib.parse import urlsplit

DEFAULTS = {
    'backend': 'ollama', 'base_url': 'http://127.0.0.1:11434', 'model': '',
    'search_provider': 'searxng', 'tavily_api_key': '', 'api_key': '', 'user_ids': [], 'admin_ids': [], 'searxng_url': '',
    'timeout_seconds': 180, 'max_tokens': 2048, 'cooldown_seconds': 5,
    'max_concurrent': 1, 'search_result_count': 5, 'search_timeout_seconds': 30,
    'system_prompt': 'Be direct. Be useful. Stick to what you can support. Say when you do not know. Do not claim to have searched the web unless search evidence was supplied.',
}


def validate_url(value, label, origin=False):
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError()
        if origin and (parsed.query or parsed.path.rstrip('/').endswith(('/api', '/v1'))):
            raise ValueError()
        _ = parsed.port
    except (ValueError, TypeError):
        raise ValueError(f'{label}: use an http(s) URL without credentials' + (' or an /api or /v1 suffix.' if origin else '.')) from None


def validate_config(config):
    if not isinstance(config, dict):
        raise ValueError('config.json must contain a JSON object.')
    for key, value in DEFAULTS.items():
        config.setdefault(key, value.copy() if isinstance(value, list) else value)
    if config['search_provider'] not in ('none', 'tavily', 'searxng'):
        raise ValueError('search_provider must be none, tavily, or searxng.')
    if config['backend'] not in ('ollama', 'openwebui', 'openai'):
        raise ValueError('backend must be ollama, openwebui, or openai.')
    for key in ('discord_token', 'tavily_api_key', 'api_key', 'model', 'system_prompt', 'searxng_url', 'base_url'):
        if not isinstance(config.get(key), str):
            raise ValueError(f'{key} must be text.')
    if not config['discord_token'].strip():
        raise ValueError('A Discord bot token is required.')
    if config['backend'] == 'openwebui' and not config['api_key'].strip():
        raise ValueError('Open WebUI needs its own API key. The Discord token goes in discord_token.')
    validate_url(config['base_url'], 'base_url', origin=True)
    if config['searxng_url']:
        validate_url(config['searxng_url'], 'searxng_url')
    for key in ('channel_ids', 'user_ids', 'admin_ids'):
        values = config.get(key)
        if not isinstance(values, list) or any(type(value) is not int or value <= 0 for value in values):
            raise ValueError(f'{key} must be a list of positive numeric Discord IDs.')
    if not config['channel_ids']:
        raise ValueError('Set at least one allowed channel ID.')
    ranges = {'timeout_seconds': (5, 1800), 'max_tokens': (1, 32768),
              'cooldown_seconds': (0, 3600), 'max_concurrent': (1, 16),
              'search_result_count': (1, 10), 'search_timeout_seconds': (5, 120)}
    for key, (minimum, maximum) in ranges.items():
        if type(config[key]) is not int or not minimum <= config[key] <= maximum:
            raise ValueError(f'{key} must be an integer from {minimum} to {maximum}.')
    return config

