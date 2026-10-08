import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from netdoctor.api import client
from netdoctor.main import queue, upload_pending


class Handler(BaseHTTPRequestHandler):
    received = []

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        self.received.append((self.path, self.headers.get("X-NetDoctor-Key"),
                              json.loads(self.rfile.read(length))))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *_args):
        pass


class ApiTests(unittest.TestCase):
    def test_registration_and_offline_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            config = {"server_url": "http://127.0.0.1:1", "api_key": "test-key",
                      "data_dir": Path(directory)}
            payload = {"schema_version": "1.0", "timestamp": "2026-01-01T00:00:00+00:00"}
            path = queue(config, payload)
            sent, errors = upload_pending(config)
            self.assertEqual(sent, 0)
            self.assertEqual(len(errors), 1)
            self.assertTrue(path.exists())
            Handler.received = []
            server = HTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                config["server_url"] = f"http://127.0.0.1:{server.server_port}"
                self.assertEqual(client.register(config, {"agent_id": "test"}), 200)
                sent, errors = upload_pending(config)
                self.assertEqual((sent, errors), (1, []))
                self.assertFalse(path.exists())
                self.assertEqual([item[0] for item in Handler.received],
                                 ["/api/v1/agents/register", "/api/v1/measurements"])
                self.assertTrue(all(item[1] == "test-key" for item in Handler.received))
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()


if __name__ == "__main__":
    unittest.main()
