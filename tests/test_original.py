# by:buf0rd | Discord LLM Connector
# Keep the setup direct. Keep credentials out of the logs.
import asyncio
import tempfile
import unittest
from types import SimpleNamespace as N
from aiohttp import web, ClientSession
from backend import Backend, BackendError
from bot import allowed, Store, trim, Bot


class Tests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.seen = []
        async def handle(request):
            self.seen.append((request.path, request.headers.get('Authorization')))
            if request.path.endswith('/models'):
                return web.json_response({'data': [{'id': 'z'}, {'id': 'a'}]})
            body = await request.json()
            self.assertFalse(body['stream'])
            self.assertEqual(body['messages'][0]['content'], 'hello')
            if body['model'] == 'fail':
                return web.Response(status=401, text='SECRET must not reach error')
            if body['model'] == 'empty':
                return web.json_response({'choices': []})
            return web.json_response({'choices': [{'message': {'content': 'world'}}]})
        app = web.Application()
        app.router.add_route('*', '/{tail:.*}', handle)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '127.0.0.1', 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        self.url = f'http://127.0.0.1:{port}'
        self.session = ClientSession()

    async def asyncTearDown(self):
        await self.session.close()
        await self.runner.cleanup()

    async def test_providers(self):
        for provider, prefix in [('ollama', '/v1'), ('openwebui', '/api'), ('openai', '/v1')]:
            b = Backend({'backend': provider, 'base_url': self.url, 'api_key': 'test-key'}, self.session)
            self.assertEqual(await b.models(), ['a', 'z'])
            self.assertEqual(await b.chat('a', [{'role': 'user', 'content': 'hello'}]), 'world')
            self.assertEqual(self.seen[-1], (prefix + '/chat/completions', 'Bearer test-key'))
            with self.assertRaisesRegex(BackendError, 'HTTP 401'):
                await b.chat('fail', [{'content': 'hello'}])
            with self.assertRaisesRegex(BackendError, 'no usable text'):
                await b.chat('empty', [{'content': 'hello'}])

    def test_access(self):
        c = {'channel_ids': [10], 'user_ids': [20]}
        m = N(guild=object(), channel=N(id=11, parent_id=10), author=N(id=20, bot=False))
        self.assertTrue(allowed(m, c))
        m.author.id = 21
        self.assertFalse(allowed(m, c))
        m.author.id = 20
        m.channel.parent_id = 9
        self.assertFalse(allowed(m, c))
        m.channel.id = 10
        m.guild = None
        self.assertFalse(allowed(m, c))

    def test_memory(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(d + '/memory.db')
            h = [{'role': 'user', 'content': 'question'}, {'role': 'assistant', 'content': 'answer'}]
            s.put('thread1', 'a', h)
            s.db.close()
            s = Store(d + '/memory.db')
            self.assertEqual(s.get('thread1', ''), ('a', h))
            self.assertEqual(s.get('thread2', 'z'), ('z', []))
            s.put('thread1', 'a', [])
            self.assertEqual(s.get('thread1', '')[1], [])
            self.assertEqual(trim(h * 20, 100000), h * 10)
            self.assertEqual(trim(h, 1), [])
            s.db.close()

    async def test_commands(self):
        with tempfile.TemporaryDirectory() as d:
            sent = []
            async def send(m, text):
                sent.append(text)
            bot = N(config={'admin_ids': [20], 'backend': 'ollama', 'system_prompt': 'test'},
                    default_model='a', store=Store(d + '/memory.db'),
                    backend=Backend({'backend': 'ollama', 'base_url': self.url}, self.session), send_text=send)
            m = N(author=N(id=21, guild_permissions=N(manage_guild=False)))
            await Bot.handle(bot, m, 'thread', '!model', 'z')
            self.assertIn('Requires', sent[-1])
            m.author.id = 20
            await Bot.handle(bot, m, 'thread', '!model', 'z')
            self.assertEqual(bot.store.get('thread', '')[0], 'z')
            await Bot.handle(bot, m, 'thread', '!reset', '')
            self.assertEqual(bot.store.get('thread', '')[1], [])
            bot.store.db.close()


if __name__ == '__main__':
    unittest.main()

