import unittest
from unittest.mock import patch
import aiohttp
from aiohttp import web
import websearch
from backend import BackendError

class TavilyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.status = 200
        self.requests = []
        async def handle(request):
            self.requests.append((request.headers.get('Authorization'), await request.json()))
            return web.json_response({'results': [{'title': 'Weather', 'url': 'https://example.com/weather', 'content': 'Cloudy', 'published_date': '2026-09-16'}]}, status=self.status)
        app = web.Application()
        app.router.add_post('/search', handle)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '127.0.0.1', 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        self.endpoint = patch.object(websearch, 'TAVILY_URL', f'http://127.0.0.1:{port}/search')
        self.endpoint.start()
        self.session = aiohttp.ClientSession()
        self.config = {'search_provider': 'tavily', 'tavily_api_key': 'test-secret', 'api_key': 'model-secret', 'searxng_url': 'http://invalid.invalid/search'}

    async def asyncTearDown(self):
        await self.session.close()
        self.endpoint.stop()
        await self.runner.cleanup()

    async def test_request_and_results(self):
        results = await websearch.search(self.config, self.session, 'weather')
        auth, payload = self.requests[0]
        self.assertEqual(auth, 'Bearer test-secret')
        self.assertEqual(payload['search_depth'], 'basic')
        self.assertFalse(payload['auto_parameters'])
        self.assertNotIn('model-secret', str(payload))
        self.assertEqual(results[0]['date'], '2026-09-16')

    async def test_errors_and_no_key(self):
        for status in (401, 403, 429, 432, 433, 500, 302):
            self.status = status
            with self.assertRaises(BackendError) as error:
                await websearch.search(self.config, self.session, 'weather')
            self.assertNotIn('test-secret', str(error.exception))
        self.config['tavily_api_key'] = ''
        self.assertFalse(websearch.search_ready(self.config))
        with self.assertRaises(BackendError):
            await websearch.search(self.config, self.session, 'weather')

