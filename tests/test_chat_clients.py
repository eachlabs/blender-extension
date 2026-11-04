import json
import os
import unittest
from unittest import mock

from eachlabs import mcp_client
from eachlabs.api_client import ApiError, EachlabsClient

from .fake_server import FakeServer
from .test_api_client import KEY, ClientTestCase

SERVER_INFO = {"name": "fake-mcp", "version": "1"}


class ChatCompletionTest(ClientTestCase):
    def test_chat_completion_sends_model_messages_tools(self):
        reply = {"choices": [{"message": {"role": "assistant", "content": "hi"}}]}
        self.server.route("POST", "/v1/chat/completions", (200, {}, reply))
        messages = [{"role": "user", "content": "make a cube"}]
        tools = [{"type": "function", "function": {"name": "add_cube", "parameters": {}}}]
        client = EachlabsClient("k", base_url=self.server.url)
        self.assertEqual(client.chat_completion("some/model", messages, tools), reply)
        request = self.server.find("POST", "/v1/chat/completions")[0]
        body = request.json()
        self.assertEqual(body["model"], "some/model")
        self.assertEqual(body["messages"], messages)
        self.assertEqual(body["tools"], tools)
        self.assertEqual(request.headers["authorization"], "Bearer k")
        self.assertNotIn("max_tokens", body)

    def test_chat_completion_waits_as_long_as_it_is_told(self):
        self.server.route("POST", "/v1/chat/completions", (200, {}, {"choices": []}))
        client = EachlabsClient("k", base_url=self.server.url)
        with mock.patch.object(client, "_open", wraps=client._open) as opened:
            client.chat_completion("m", [], [])
            client.chat_completion("m", [], [], timeout=77.0)
        self.assertEqual([call.args[1] for call in opened.call_args_list], [120.0, 77.0])

    def test_chat_completion_sends_max_tokens(self):
        self.server.route("POST", "/v1/chat/completions", (200, {}, {"choices": []}))
        EachlabsClient("k", base_url=self.server.url).chat_completion("m", [], [], max_tokens=4096)
        self.assertEqual(self.server.find("POST", "/v1/chat/completions")[0].json()["max_tokens"], 4096)

    def test_chat_completion_can_turn_reasoning_off(self):
        self.server.route("POST", "/v1/chat/completions", (200, {}, {"choices": []}))
        client = EachlabsClient("k", base_url=self.server.url)
        client.chat_completion("m", [], [])
        client.chat_completion("m", [], [], reasoning=False)
        bodies = [r.json() for r in self.server.find("POST", "/v1/chat/completions")]
        self.assertNotIn("reasoning", bodies[0])
        self.assertEqual(bodies[1]["reasoning"], {"enabled": False})

    def test_chat_completion_401_is_readable(self):
        self.server.route("POST", "/v1/chat/completions", (401, {}, b""))
        with self.assertRaises(ApiError) as caught:
            self.client.chat_completion("m", [], [])
        self.assertEqual(caught.exception.message, "Invalid or missing API key (HTTP 401)")

    def test_rate_limit_shown_as_400_is_flagged(self):
        body = {"error": {"message": "Rate limit exceeded. Please retry after a short delay."}}
        self.server.route("POST", "/v1/chat/completions", (400, {}, body))
        with self.assertRaises(ApiError) as caught:
            self.client.chat_completion("m", [], [])
        self.assertTrue(caught.exception.rate_limited)
        self.server.route("POST", "/v1/chat/completions", (400, {}, {"error": {"message": "messages is required"}}))
        with self.assertRaises(ApiError) as caught:
            self.client.chat_completion("m", [], [])
        self.assertFalse(caught.exception.rate_limited)

    def test_rate_limited_needs_status_and_word(self):
        self.assertTrue(ApiError("Rate limit exceeded", status=429).rate_limited)
        self.assertFalse(ApiError("Request failed", status=429).rate_limited)
        self.assertFalse(ApiError("Rate limit exceeded", status=500).rate_limited)
        self.assertFalse(ApiError("Rate limit exceeded").rate_limited)


class McpUrlTest(unittest.TestCase):
    def test_mcp_url(self):
        self.assertEqual(mcp_client.mcp_url("https://api.eachlabs.ai", None), "https://mcp.eachlabs.ai/mcp")
        self.assertEqual(mcp_client.mcp_url("https://api.eachlabs.ai/", None), "https://mcp.eachlabs.ai/mcp")
        self.assertEqual(mcp_client.mcp_url("http://127.0.0.1:9", "http://127.0.0.1:9/mcp"), "http://127.0.0.1:9/mcp")
        self.assertIsNone(mcp_client.mcp_url("http://127.0.0.1:9", None))
        self.assertIsNone(mcp_client.mcp_url("http://127.0.0.1:9", "  "))

    def test_mcp_url_validates_override_and_base(self):
        self.assertEqual(mcp_client.mcp_url("http://127.0.0.1:9", "https://mcp.example.com/mcp"),
                         "https://mcp.example.com/mcp")
        self.assertIsNone(mcp_client.mcp_url("http://127.0.0.1:9", "ftp://mcp.example.com/mcp"))
        self.assertIsNone(mcp_client.mcp_url("http://127.0.0.1:9", "http://mcp.example.com/mcp"))
        self.assertIsNone(mcp_client.mcp_url("not a url", "https://mcp.example.com/mcp"))
        self.assertIsNone(mcp_client.mcp_url("", "https://mcp.example.com/mcp"))


def _rpc(record, result):
    return {"jsonrpc": "2.0", "id": record.json()["id"], "result": result}


class McpClientTest(unittest.TestCase):
    def setUp(self):
        self.server = FakeServer().__enter__()
        self.url = self.server.url + "/mcp"

    def tearDown(self):
        self.server.__exit__()

    def test_mcp_initialize_json_and_sse(self):
        calls = []

        def handler(record):
            body = record.json()
            calls.append(body)
            method = body.get("method")
            if method == "initialize":
                return 200, {"mcp-session-id": "sess-1"}, _rpc(record, {"serverInfo": SERVER_INFO})
            if method == "notifications/initialized":
                return 202, {}, b""
            progress = {"jsonrpc": "2.0", "method": "notifications/progress", "params": {"progress": 1}}
            final = _rpc(record, {"tools": [{"name": "t"}]})
            sse = "event: message\ndata: %s\n\nevent: message\ndata: %s\n\n" % (json.dumps(progress), json.dumps(final))
            return 200, {"Content-Type": "text/event-stream"}, sse.encode("utf-8")

        self.server.route("POST", "/mcp", handler)
        client = mcp_client.McpClient(self.url, KEY)
        self.assertEqual(client.initialize(), SERVER_INFO)
        self.assertEqual(client.list_tools(), [{"name": "t"}])
        requests = self.server.find("POST", "/mcp")
        self.assertEqual([c.get("method") for c in calls], ["initialize", "notifications/initialized", "tools/list"])
        self.assertEqual([c.get("id") for c in calls], [1, None, 2])
        self.assertNotIn("mcp-session-id", requests[0].headers)
        self.assertEqual(requests[1].headers["mcp-session-id"], "sess-1")
        self.assertEqual(requests[2].headers["mcp-session-id"], "sess-1")
        self.assertEqual(requests[0].headers["authorization"], "Bearer " + KEY)
        self.assertIn("text/event-stream", requests[0].headers["accept"])

    def test_list_tools_follows_next_cursor(self):
        def handler(record):
            body = record.json()
            if "id" not in body:
                return 202, {}, b""
            if body["method"] == "initialize":
                return 200, {}, _rpc(record, {"serverInfo": SERVER_INFO})
            if (body.get("params") or {}).get("cursor") == "c2":
                return 200, {}, _rpc(record, {"tools": [{"name": "b"}]})
            return 200, {}, _rpc(record, {"tools": [{"name": "a"}], "nextCursor": "c2"})

        self.server.route("POST", "/mcp", handler)
        client = mcp_client.McpClient(self.url, KEY)
        client.initialize()
        self.assertEqual([t["name"] for t in client.list_tools()], ["a", "b"])

    def test_rpc_error_raises(self):
        error = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32600, "message": "bad"}}
        self.server.route("POST", "/mcp", (200, {}, error))
        with self.assertRaises(ApiError) as caught:
            mcp_client.McpClient(self.url, KEY).initialize()
        self.assertIn("bad", caught.exception.message)

    def test_mcp_check_bad_key(self):
        self.server.route("POST", "/mcp", (401, {}, b""))
        with mock.patch.dict(os.environ, {"EACHLABS_MCP_URL": self.url}):
            self.assertEqual(mcp_client.check(self.server.url, "bad"), (False, "API key was rejected (HTTP 401)."))

    def test_redirect_is_not_followed(self):
        self.server.route("POST", "/mcp", (302, {"Location": "/other"}, b""))
        self.server.route("POST", "/other", (200, {}, {}))
        with mock.patch.dict(os.environ, {"EACHLABS_MCP_URL": self.url}):
            ok, text = mcp_client.check(self.server.url, KEY)
        self.assertFalse(ok)
        self.assertIn("redirects", text)
        self.assertEqual(self.server.find("POST", "/other"), [])
        self.assertEqual(len(self.server.requests), 1)

    def test_mcp_check_connected(self):
        def handler(record):
            body = record.json()
            if "id" not in body:
                return 202, {}, b""
            if body["method"] == "initialize":
                return 200, {}, _rpc(record, {"serverInfo": SERVER_INFO})
            return 200, {}, _rpc(record, {"tools": []})

        self.server.route("POST", "/mcp", handler)
        with mock.patch.dict(os.environ, {"EACHLABS_MCP_URL": self.url}):
            self.assertEqual(mcp_client.check(self.server.url, KEY), (True, "MCP connected"))

    def test_mcp_check_without_address(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("EACHLABS_MCP_URL", None)
            ok, text = mcp_client.check(self.server.url, KEY)
        self.assertFalse(ok)
        self.assertIn("EACHLABS_MCP_URL", text)
        self.assertNotIn("\n", text)


if __name__ == "__main__":
    unittest.main()
