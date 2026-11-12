# by:buf0rd | Discord LLM Connector
# Keep the setup direct. Keep credentials out of the logs.
import json
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import aiohttp
from aiohttp import web
from backend import BackendError
from websearch import search, search_url, answer_search, normalize_results
from patch_bot import patch_bot


class SearchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.queries = []
        async def handler(req):
            self.queries.append(dict(req.query))
            q = req.query.get('q')
            if q in ('403', '429'):
                return web.Response(status=int(q))
            if q == 'html':
                return web.Response(text='<html>login</html>')
            if q == 'redirect':
                return web.Response(status=302, headers={'Location': 'https://example.com'})
            if q == 'large':
                return web.Response(body=b'x' * 2_000_001)
            if q == 'empty':
                return web.json_response({'results': []})
            return web.json_response({'results': [
                {'title': '<b>Result</b>', 'content': 'Evidence &amp; details.', 'url': 'https://example.com/a'},
                {'content': 'duplicate', 'url': 'https://example.com/a#fragment'},
                {'content': 'bad', 'url': 'javascript:alert(1)'},
                {'content': 'bad', 'url': 'https://user:secret@example.com'},
                {'content': 'second', 'url': 'https://example.org/b'},
            ]})
        app = web.Application()
        app.router.add_get('/search', handler)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '127.0.0.1', 0)
        await site.start()
        self.url = f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/search'
        self.session = aiohttp.ClientSession()
        self.config = {'searxng_url': self.url}

    async def asyncTearDown(self):
        await self.session.close()
        await self.runner.cleanup()

    async def test_query_encoding_and_normalization(self):
        self.config['searxng_url'] += '?q=<query>&format=html&language=en'
        results = await search(self.config, self.session, 'a & b? café')
        self.assertEqual(self.queries[-1], {'q': 'a & b? café', 'format': 'json', 'language': 'en'})
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]['snippet'], 'Evidence & details.')
        self.assertEqual(results[0]['title'], 'Result')
        self.assertEqual(results[1]['id'], 2)
        self.assertEqual(normalize_results({'results': [None, {}, {'url': 'https://x', 'content': ''}]}, 5), [])

    async def test_failure_messages(self):
        for q, message in [('403', '403'), ('429', 'rate limit'), ('html', 'non-JSON'),
                           ('redirect', 'redirected'), ('large', '2 MB')]:
            with self.subTest(query=q), self.assertRaisesRegex(BackendError, message):
                await search(self.config, self.session, q)

    async def test_answer_and_no_results(self):
        send = AsyncMock()
        backend = N(chat=AsyncMock(return_value='Answer [1].'), models=AsyncMock(return_value=['a']))
        bot = N(config=self.config, session=self.session, backend=backend, send_text=send)
        await answer_search(bot, object(), 'selected-model', 'question')
        args = backend.chat.call_args.args
        self.assertEqual(args[0], 'selected-model')
        self.assertIn('untrusted', args[1][0]['content'])
        evidence = json.loads(args[1][1]['content'])
        self.assertEqual(evidence['question'], 'question')
        self.assertIn('<https://example.com/a>', send.call_args.args[1])
        backend.chat.reset_mock()
        await answer_search(bot, object(), 'a', 'empty')
        backend.chat.assert_not_called()
        await answer_search(bot, object(), 'a', '')
        self.assertIn('Usage:', send.call_args.args[1])

    async def test_model_failure_keeps_links(self):
        bot = N(config=self.config, session=self.session,
                backend=N(chat=AsyncMock(side_effect=BackendError('Backend unavailable'))), send_text=AsyncMock())
        await answer_search(bot, object(), 'a', 'question')
        self.assertIn('model generation failed', bot.send_text.call_args.args[1])
        self.assertIn('https://example.com/a', bot.send_text.call_args.args[1])

    def test_bad_config_and_url_template(self):
        for raw in ('', 'file:///etc/passwd', 'http://user:pass@host/search'):
            with self.assertRaises(BackendError):
                search_url({'searxng_url': raw}, 'test')
        url = search_url({'searxng_url': 'https://example.com//search?q=<query>'}, 'test')
        self.assertEqual(urlsplit(url).path, '/search')

    def test_patcher_idempotence_and_guards(self):
        source = Path(__file__).with_name('bot.py').read_text()
        modified = patch_bot(source)
        self.assertEqual(patch_bot(modified), modified)
        with self.assertRaises(ValueError):
            patch_bot('unrecognized bot')

    async def test_command_dispatch_and_allowlist(self):
        import bot as module
        from discord import AllowedMentions
        config = {'model': 'a', 'channel_ids': [10], 'user_ids': [], 'admin_ids': [], 'cooldown_seconds': 0}
        client = module.Bot(config)
        client._connection.user = N(id=99)
        client.scope = 'test|'
        @asynccontextmanager
        async def typing():
            yield
        message = N(guild=N(id=1), author=N(id=20, bot=False), mentions=[], content='!search hello',
                    channel=N(id=10, typing=typing))
        client.handle = AsyncMock()
        await client.on_message(message)
        self.assertEqual(client.handle.call_args.args[2:], ('!search', 'hello'))
        client.handle.reset_mock()
        message.channel.id = 12
        await client.on_message(message)
        client.handle.assert_not_called()
        self.assertFalse(client.allowed_mentions.everyone)
        await client.close()


if __name__ == '__main__':
    unittest.main()

