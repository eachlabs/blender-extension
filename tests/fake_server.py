"""A local HTTP server with scripted responses, so the client is tested through real urllib."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


class Recorded:
    def __init__(self, method, path, query, headers, body):
        self.method = method
        self.path = path
        self.query = query
        self.headers = headers
        self.body = body

    def json(self):
        return json.loads(self.body.decode("utf-8"))


class FakeServer:
    def __init__(self):
        self.routes = {}
        self.requests = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _handle(self):
                parsed = urlparse(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                record = Recorded(self.command, parsed.path, parse_qs(parsed.query),
                                  {k.lower(): v for k, v in self.headers.items()}, body)
                server.requests.append(record)
                route = server.routes.get((self.command, parsed.path))
                if route is None:
                    status, headers, payload = 404, {}, b'{"error":"no route"}'
                else:
                    status, headers, payload = route(record) if callable(route) else route
                if not isinstance(payload, bytes):
                    payload = json.dumps(payload).encode("utf-8")
                    headers = dict({"Content-Type": "application/json"}, **headers)
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = do_PUT = do_DELETE = _handle

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()

    def route(self, method, path, response):
        self.routes[(method, path)] = response

    def find(self, method, path):
        return [r for r in self.requests if r.method == method and r.path == path]
