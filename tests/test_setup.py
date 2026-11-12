# by:buf0rd | Test the parts that have actually bitten us.
import ast
import json
import os
from pathlib import Path
import pty
import select
import sys
import time
import unittest
from settings import validate_config
from websearch import answer_search
from types import SimpleNamespace as N
from unittest.mock import AsyncMock


class SetupTests(unittest.IsolatedAsyncioTestCase):
    def test_config_validation(self):
        config = validate_config({'discord_token': 'placeholder', 'channel_ids': [123]})
        self.assertEqual(config['backend'], 'ollama')
        self.assertEqual(config['searxng_url'], '')
        for changes in ({'channel_ids': []}, {'channel_ids': ['123']},
                        {'backend': 'openwebui', 'api_key': ''}, {'base_url': 'http://host/v1'},
                        {'search_result_count': 0}, {'cooldown_seconds': True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_config(dict(config, **changes))

    def test_actual_terminal_prompt(self):
        # Execute the exact shipped prompt in a real PTY. Mocks missed the r+ bug.
        tree = ast.parse(Path(__file__).with_name('configure.py').read_text())
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'prompt')
        code = ast.unparse(function) + "\nprint('VALUE=' + prompt('Backend', 'ollama'), flush=True)"
        child_pid, terminal_fd = pty.fork()
        if child_pid == 0:
            os.execv(sys.executable, [sys.executable, '-c', code])
        transcript = b''
        sent = False
        deadline = time.monotonic() + 5
        try:
            while time.monotonic() < deadline:
                if select.select([terminal_fd], [], [], 0.1)[0]:
                    try:
                        chunk = os.read(terminal_fd, 4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    transcript += chunk
                    if b'[ollama]:' in transcript and not sent:
                        os.write(terminal_fd, b'openwebui\n')
                        sent = True
            ended, status = os.waitpid(child_pid, os.WNOHANG)
            if not ended:
                # Allow a short scheduling gap after the terminal has closed.
                for _ in range(20):
                    time.sleep(0.01)
                    ended, status = os.waitpid(child_pid, os.WNOHANG)
                    if ended:
                        break
            if not ended:
                os.kill(child_pid, 9)
                os.waitpid(child_pid, 0)
                self.fail('Terminal prompt timed out.')
            self.assertEqual(os.waitstatus_to_exitcode(status), 0, transcript)
            self.assertIn(b'VALUE=openwebui', transcript)
        finally:
            os.close(terminal_fd)

    async def test_unconfigured_search_does_not_touch_backend(self):
        connector = N(config={'searxng_url': ''}, send_text=AsyncMock(), backend=N(chat=AsyncMock()))
        await answer_search(connector, object(), 'a', 'question')
        connector.backend.chat.assert_not_called()
        self.assertIn('not configured', connector.send_text.call_args.args[1])


if __name__ == '__main__':
    unittest.main()

