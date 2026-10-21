"""Experimental LWP frame/transport tests (local echo server)."""

from __future__ import annotations

import json
import threading
import unittest
from unittest.mock import patch

from websockets.sync.server import serve

from test_core import BaseCase
from fap.platform import lwp, lwp_frames


class LWPFrameTests(BaseCase):
    def test_register_and_text_shape(self):
        reg = lwp_frames.build_register_frame()
        self.assertEqual(reg["lwp"], "/reg")
        self.assertEqual(reg["headers"]["app-key"], lwp_frames.APP_KEY)
        self.assertEqual(reg["body"], {})
        text = lwp_frames.build_text_frame("conv-1", "buyer-1", "你好")
        self.assertEqual(text["lwp"], "/r/MessageSend/sendByReceiverScope")
        self.assertEqual(text["body"]["conversationId"], "conv-1")
        self.assertEqual(text["body"]["receiver"]["userId"], "buyer-1")
        self.assertEqual(text["body"]["message"]["text"]["text"], "你好")
        self.assertTrue(text["headers"]["mid"])

    def test_optional_header_keys(self):
        reg = lwp_frames.build_register_frame(
            token="tok", device_id="did-1", mid="mid-1", dt="1", wv="1", sync="1",
            cache_header="cache-1")
        self.assertEqual(reg["headers"]["token"], "tok")
        self.assertEqual(reg["headers"]["did"], "did-1")
        self.assertEqual(reg["headers"]["mid"], "mid-1")
        self.assertEqual(reg["headers"]["cache-header"], "cache-1")
        self.assertNotIn("token", lwp_frames.build_register_frame()["headers"])

    def test_exchange_with_local_echo(self):
        seen = []

        def handler(ws):
            for raw in ws:
                frame = json.loads(raw)
                seen.append(frame["lwp"])
                ws.send(json.dumps({"echo": frame["lwp"]}))

        server = serve(handler, "127.0.0.1", 0)
        port = server.socket.getsockname()[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.object(lwp, "WS_URL", f"ws://127.0.0.1:{port}/account"):
                result = lwp.exchange("test-token", [
                    lwp_frames.build_register_frame(),
                    lwp_frames.build_text_frame("c1", "u1", "hi"),
                ], timeout=3)
        finally:
            server.shutdown()
            thread.join(timeout=3)
        self.assertTrue(result["connected"], result)
        self.assertEqual([r["echo"] for r in result["responses"]],
                         ["/reg", "/r/MessageSend/sendByReceiverScope"])
        self.assertEqual(seen, ["/reg", "/r/MessageSend/sendByReceiverScope"])


if __name__ == "__main__":
    unittest.main()
