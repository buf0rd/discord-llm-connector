# by:buf0rd | Discord LLM Connector
# Keep the setup direct. Keep credentials out of the logs.
import asyncio
import json
import aiohttp


class BackendError(Exception):
    pass


class Backend:
    def __init__(self, config, session):
        self.config, self.session = config, session
        backend_origin = config['base_url'].rstrip('/')
        api_prefix = '/api' if config['backend'] == 'openwebui' else '/v1'
        self.chat_url = backend_origin + api_prefix + '/chat/completions'
        self.models_url = backend_origin + api_prefix + '/models'

    async def request(self, method, url, payload=None):
        headers = {}
        if self.config.get('api_key'):
            headers['Authorization'] = 'Bearer ' + self.config['api_key']
        try:
            async with self.session.request(method, url, json=payload, headers=headers,
                    allow_redirects=False,
                    timeout=aiohttp.ClientTimeout(total=self.config.get('timeout_seconds', 180))) as http_response:
                if http_response.status != 200:
                    raise BackendError(f'Backend HTTP {http_response.status}; check endpoint, credentials, and model.')
                raw = bytearray()
                async for chunk in http_response.content.iter_chunked(65536):
                    raw.extend(chunk)
                    if len(raw) > 2_000_000:
                        raise BackendError('Backend response exceeded 2 MB.')
                try:
                    return json.loads(raw)
                except (ValueError, UnicodeError):
                    raise BackendError('Backend returned invalid JSON; disable forced streaming if enabled.') from None
        except (aiohttp.ClientError, asyncio.TimeoutError):
            raise BackendError('Backend unavailable or timed out; check the service and network.') from None

    async def models(self):
        data = await self.request('GET', self.models_url)
        if not isinstance(data, dict) or not isinstance(data.get('data'), list):
            raise BackendError('Invalid model-list response.')
        return sorted({model_entry['id'] for model_entry in data['data'] if isinstance(model_entry, dict) and isinstance(model_entry.get('id'), str)})

    async def chat(self, model, messages):
        data = await self.request('POST', self.chat_url, {
            'model': model, 'messages': messages, 'stream': False,
            'max_tokens': self.config.get('max_tokens', 2048),
        })
        try:
            message = data['choices'][0]['message']
            answer = message['content']
            if message.get('tool_calls'):
                raise BackendError('Backend requested client-side tools; this bridge does not execute tools.')
            if not isinstance(answer, str) or not answer.strip():
                raise ValueError()
            return answer.strip()
        except (KeyError, IndexError, TypeError, ValueError):
            raise BackendError('Backend returned no usable text completion.') from None

