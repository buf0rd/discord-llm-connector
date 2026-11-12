# by:buf0rd | Discord LLM Connector
# Ask for what we need. Keep the token out of the terminal output.
import argparse
import getpass
import json
import os
from pathlib import Path
import tempfile
from settings import DEFAULTS, validate_config

CONFIG_PATH = Path('/etc/discord-llm/config.json')


def prompt(label, default=''):
    # A terminal isn't seekable. Use separate read/write handles, not r+.
    with open('/dev/tty', 'w') as output, open('/dev/tty', 'r') as terminal:
        output.write(f'{label} [{default}]: ')
        output.flush()
        answer = terminal.readline()
        if not answer:
            raise SystemExit('No terminal input. Run setup from an interactive terminal.')
        answer = answer.strip()
        return '' if answer == '-' else answer or default


def secret(label, previous=''):
    value = getpass.getpass(label + ' (hidden; Enter keeps it, - clears it): ').strip()
    return '' if value == '-' else value or previous


def prompt_ids(label, previous):
    while True:
        value = prompt(label, ','.join(map(str, previous)))
        try:
            numbers = [int(item.strip()) for item in value.split(',') if item.strip()]
            if any(number <= 0 for number in numbers):
                raise ValueError()
            return list(dict.fromkeys(numbers))
        except ValueError:
            print('Use numeric IDs, separated by commas.')


def collect_config(previous):
    config = dict(previous)
    print('\nDiscord LLM Connector // by:buf0rd')
    print('Enter keeps the shown value. A single - clears an optional value.')
    backend = prompt('Backend: ollama / openwebui / openai', config.get('backend', 'ollama')).lower()
    if backend not in ('ollama', 'openwebui', 'openai'):
        raise ValueError('Choose ollama, openwebui, or openai.')
    same_backend = backend == config.get('backend', 'ollama')
    default_url = 'http://127.0.0.1:3000' if backend == 'openwebui' else 'http://127.0.0.1:11434'
    config['backend'] = backend
    config['base_url'] = prompt('Backend URL, before /api or /v1', config.get('base_url', default_url) if same_backend else default_url).rstrip('/')
    config['discord_token'] = secret('Discord BOT token', config.get('discord_token', ''))
    print('The backend API key is separate from the Discord token. Direct Ollama usually needs none.')
    config['api_key'] = secret('Backend API key', config.get('api_key', '') if same_backend else '')
    config['channel_ids'] = prompt_ids('Allowed CHANNEL IDs, required', config.get('channel_ids', []))
    config['user_ids'] = prompt_ids('Allowed USER IDs; blank means everyone in allowed channels', config.get('user_ids', []))
    config['admin_ids'] = prompt_ids('Bot admin USER IDs; Manage Server members also qualify', config.get('admin_ids', []))
    config['model'] = prompt('Exact chat model ID; blank selects first available alphabetically', config.get('model', '') if same_backend else '')
    config['search_provider'] = prompt('Search: none / tavily / searxng', config.get('search_provider', 'searxng' if config.get('searxng_url') else 'none')).lower()
    if config['search_provider'] == 'tavily':
        config['tavily_api_key'] = secret('Tavily API key', config.get('tavily_api_key', ''))
        if not config['tavily_api_key']:
            raise ValueError('Tavily needs its own API key.')
    elif config['search_provider'] == 'searxng':
        config['searxng_url'] = prompt('SearXNG search URL', config.get('searxng_url', ''))
    return validate_config(config)


def write_config(path, config, service_group=True):
    import grp
    # Write first, replace second. A partial JSON file isn't a config.
    mode = 0o640 if service_group else 0o600
    gid = grp.getgrnam('discord-llm').gr_gid if service_group else os.getgid()
    fd, temporary = tempfile.mkstemp(prefix='.config-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as output:
            json.dump(config, output, indent=2)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
            os.fchmod(output.fileno(), mode)
            os.fchown(output.fileno(), os.getuid(), gid)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    parser.add_argument('--keep-existing', action='store_true')
    args = parser.parse_args()
    previous = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}
    if args.keep_existing and previous:
        config = validate_config(previous)
        print('Keeping the existing config. Added missing defaults.')
    else:
        config = collect_config(previous)
    destination = args.output or CONFIG_PATH
    write_config(destination, config, service_group=not bool(args.output))
    print('Config saved.' + (' Restart discord-llm to use it.' if not args.output else ''))


if __name__ == '__main__':
    os.umask(0o077)
    try:
        main()
    except (ValueError, OSError) as error:
        raise SystemExit(f'Setup stopped: {error}') from None

