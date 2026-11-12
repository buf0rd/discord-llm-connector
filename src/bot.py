# by:buf0rd | Discord LLM Connector
# Keep the setup direct. Keep credentials out of the logs.
import asyncio
import io
import json
import logging
import os
import sqlite3
import time
from pathlib import Path

import aiohttp
import discord
from backend import Backend, BackendError
from websearch import answer_search, search_ready
from settings import validate_config
# discord-llm explicit-search v1

LOG = logging.getLogger('discord-llm')
HELP = '''Mention me or use !ask <question>.
!search <question> — search the web and summarize snippets with source links
!models — available models
!model — current model
!status — backend connectivity
!help — commands
!model <exact model ID> — change this conversation's model (admin)
!reset — erase this conversation's memory (admin)
Memory is shared by participants in this channel/thread; threads have separate memory.'''


def allowed(message, config):
    if message.guild is None or message.author.bot:
        return False
    ids = config['channel_ids']
    if message.channel.id not in ids and getattr(message.channel, 'parent_id', None) not in ids:
        return False
    return not config['user_ids'] or message.author.id in config['user_ids']


def trim(history, limit):
    history = history[-20:]
    while history and sum(len(history_message['content']) for history_message in history) > limit:
        history = history[2:]
    return history


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, model TEXT, history TEXT, updated REAL)')
        self.db.execute('DELETE FROM conversations WHERE updated < ?', (time.time() - 7 * 86400,))
        self.db.commit()

    def get(self, conversation_key, default):
        database_row = self.db.execute('SELECT model,history,updated FROM conversations WHERE id=?', (conversation_key,)).fetchone()
        if not database_row or database_row[2] < time.time() - 7 * 86400:
            return default, []
        return database_row[0], json.loads(database_row[1])

    def put(self, conversation_key, model, history):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO conversations VALUES (?,?,?,?)',
                            (conversation_key, model, json.dumps(history), time.time()))
            self.db.execute('DELETE FROM conversations WHERE updated < ?', (time.time() - 7 * 86400,))


class Bot(discord.Client):
    def __init__(self, config):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none(), max_messages=100)
        self.config = config
        self.active = set()
        self.cooldowns = {}
        self.default_model = config['model']

    async def setup_hook(self):
        self.session = aiohttp.ClientSession()
        self.backend = Backend(self.config, self.session)
        path = Path(os.environ.get('STATE_DIRECTORY', '/var/lib/discord-llm'))
        path.mkdir(parents=True, exist_ok=True)
        # Different backend, different conversation. Don't carry old context across servers.
        self.scope = self.config['backend'] + '|' + self.config['base_url'] + '|'
        self.store = Store(path / 'memory.sqlite3')

    async def close(self):
        if hasattr(self, 'session'):
            await self.session.close()
        if hasattr(self, 'store'):
            self.store.db.close()
        await super().close()

    async def on_ready(self):
        LOG.info('Connected as bot ID %s', self.user.id)
        # A login isn't a server invite. Say when the bot cannot see the configured channel.
        for channel_id in self.config['channel_ids']:
            try:
                channel = self.get_channel(channel_id) or await self.fetch_channel(channel_id)
                if getattr(channel, 'guild', None) is None:
                    LOG.warning('Channel %s is not a server channel.', channel_id)
                    continue
                member = channel.guild.me
                if member is not None:
                    permissions = channel.permissions_for(member)
                    required = ['view_channel', 'read_message_history', 'attach_files']
                    required.append('send_messages_in_threads' if isinstance(channel, discord.Thread) else 'send_messages')
                    missing = [name for name in required if not getattr(permissions, name)]
                    if missing:
                        LOG.warning('Channel %s needs permissions: %s', channel_id, ', '.join(missing))
            except discord.HTTPException:
                LOG.warning('Cannot access channel %s. Check the server invite, channel ID, and channel permissions.', channel_id)

    async def send_text(self, message, text):
        if len(text) > 5700:
            await message.reply('Response attached.', file=discord.File(io.BytesIO(text.encode()), filename='response.txt'), mention_author=False)
        else:
            for pos in range(0, len(text), 1900):
                await message.reply(text[pos:pos + 1900], mention_author=False)

    async def on_message(self, message):
        if not allowed(message, self.config):
            return
        text = message.content.strip()
        mentioned = self.user in message.mentions
        for tag in (f'<@{self.user.id}>', f'<@!{self.user.id}>'):
            text = text.replace(tag, '').strip()
        # Accept spaces, tabs, and newlines after the command.
        parts = text.split(maxsplit=1)
        command_word, command_text = (parts[0], parts[1] if len(parts) > 1 else '') if parts else ('', '')
        command = command_word.lower()
        commands = {'!ask', '!search', '!models', '!model', '!reset', '!status', '!help'}
        if command not in commands and not mentioned:
            return
        if command not in commands:
            command, command_text = '!ask', text
        conversation_key = self.scope + str(message.guild.id) + ':' + str(message.channel.id)
        current_time = time.monotonic()
        user_id = message.author.id
        if current_time - self.cooldowns.get(user_id, -999) < self.config.get('cooldown_seconds', 5):
            return
        self.cooldowns = {k: v for k, v in self.cooldowns.items() if current_time - v < 60}
        self.cooldowns[user_id] = current_time
        try:
            if conversation_key in self.active or len(self.active) >= self.config.get('max_concurrent', 1):
                await self.send_text(message, 'The bot is busy. Try again after the current response.')
                return
            self.active.add(conversation_key)
            try:
                async with message.channel.typing():
                    await self.handle(message, conversation_key, command, command_text.strip())
            finally:
                self.active.discard(conversation_key)
        except BackendError as exc:
            LOG.warning('%s', exc)
            await self.send_text(message, str(exc))
        except discord.HTTPException as exc:
            LOG.warning('Discord delivery failed: HTTP %s', exc.status)
        except Exception as exc:
            # Do not log prompts, tokens, or backend response bodies.
            LOG.error('Request failed: %s', type(exc).__name__)
            await self.send_text(message, 'Request failed; check the service logs.')

    async def handle(self, message, conversation_key, command, command_text):
        admin = message.author.id in self.config['admin_ids'] or message.author.guild_permissions.manage_guild
        model, history = self.store.get(conversation_key, self.default_model)
        if command == '!help':
            return await self.send_text(message, HELP)
        if command == '!reset' or (command == '!model' and command_text):
            if not admin:
                return await self.send_text(message, 'Requires a configured bot admin or Manage Server permission.')
            if command == '!reset':
                self.store.put(conversation_key, model, [])
                return await self.send_text(message, 'Conversation memory cleared.')
            models = await self.backend.models()
            if command_text not in models:
                return await self.send_text(message, 'Unknown model ID. Use !models for exact IDs.')
            self.store.put(conversation_key, command_text, [])
            return await self.send_text(message, f'Model set to {command_text}. Conversation memory cleared.')
        if command in {'!models', '!status'}:
            models = await self.backend.models()
            output = '\n'.join(models) or 'No models available.'
            if command == '!status':
                output = f'Backend: {self.config["backend"]}; reachable. {len(models)} model(s). Current: {model or "automatic"}. Memory: {len(history)//2} turns.'
                output += '\n!search: ' + ('configured; checked when you search.' if search_ready(self.config) else 'not configured yet.')
            return await self.send_text(message, output)
        if command == '!model':
            return await self.send_text(message, 'Current model: ' + (model or 'automatic; resolved on first question'))
        if command == '!search':
            return await answer_search(self, message, model, command_text)
        if not command_text:
            return await self.send_text(message, HELP)
        if len(command_text) > 8000:
            return await self.send_text(message, 'Limit questions to 8,000 characters.')
        if not model:
            models = await self.backend.models()
            if not models:
                raise BackendError('No models available. Install or configure a chat model on the backend.')
            model = self.default_model = models[0]
        history = trim(history, 24000 - len(command_text))
        user = {'role': 'user', 'content': command_text}
        answer = await self.backend.chat(model, [{'role': 'system', 'content': self.config['system_prompt']}] + history + [user])
        await self.send_text(message, answer)
        self.store.put(conversation_key, model, trim(history + [user, {'role': 'assistant', 'content': answer}], 24000))


if __name__ == '__main__':
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    with open(os.environ.get('BOT_CONFIG', '/etc/discord-llm/config.json')) as config_file:
        config = json.load(config_file)
    validate_config(config)
    Bot(config).run(config['discord_token'], log_handler=None)

