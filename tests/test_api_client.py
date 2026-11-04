import os
import socket
import tempfile
import threading
import unittest
import urllib.request
from unittest import mock

from eachlabs import api_client
from eachlabs.api_client import ApiError, EachlabsClient

from .fake_server import FakeServer

KEY = "test-key-123"


class ClientTestCase(unittest.TestCase):
    def setUp(self):
        self.server = FakeServer().__enter__()
        self.client = EachlabsClient(KEY, base_url=self.server.url, user_agent="eachlabs-blender/test")
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.server.__exit__()
        self.tmp.cleanup()


class CatalogTest(ClientTestCase):
    def test_pages_models_by_100_without_auth(self):
        pages = {0: [{"slug": "m%d" % i} for i in range(100)],
                 100: [{"slug": "m%d" % i} for i in range(100, 200)],
                 200: [{"slug": "m200"}]}
        self.server.route("GET", "/v1/models",
                          lambda r: (200, {}, pages[int(r.query["offset"][0])]))
        models = self.client.list_models()
        self.assertEqual(len(models), 201)
        calls = self.server.find("GET", "/v1/models")
        self.assertEqual([c.query["offset"][0] for c in calls], ["0", "100", "200"])
        self.assertEqual({c.query["limit"][0] for c in calls}, {"100"})
        self.assertTrue(all("authorization" not in c.headers for c in calls))
        self.assertEqual(calls[0].headers["user-agent"], "eachlabs-blender/test")

    def test_get_model_quotes_slug(self):
        self.server.route("GET", "/v1/models/a%2Fb", (200, {}, {"slug": "a/b", "cost": None}))
        self.assertEqual(self.client.get_model("a/b")["slug"], "a/b")

    def test_workflows_follow_next_offset(self):
        def page(r):
            offset = int(r.query["offset"][0])
            if offset == 0:
                return 200, {}, {"workflows": [{"workflow_id": str(i)} for i in range(100)], "offset": 100}
            return 200, {}, {"workflows": [{"workflow_id": "last"}], "total_count": 101}
        self.server.route("GET", "/v1/workflows", page)
        rows = self.client.list_workflows()
        self.assertEqual(len(rows), 101)
        self.assertEqual(self.server.find("GET", "/v1/workflows")[0].headers["authorization"], "Bearer " + KEY)

    def test_balance(self):
        self.server.route("GET", "/v1/billing/balance", (200, {}, {"balance_usd": 12.5}))
        self.assertEqual(self.client.get_balance()["balance_usd"], 12.5)


class ErrorTest(ClientTestCase):
    def test_empty_401_becomes_readable(self):
        self.server.route("GET", "/v1/billing/balance", (401, {}, {}))
        with self.assertRaises(ApiError) as ctx:
            self.client.get_balance()
        self.assertEqual(ctx.exception.message, "Invalid or missing API key (HTTP 401)")
        self.assertEqual(ctx.exception.status, 401)
        self.assertFalse(ctx.exception.transient)

    def test_api_error_text_and_validation_details(self):
        self.server.route("POST", "/v1/prediction", (400, {}, {
            "status": 400, "error": "Invalid request",
            "details": [{"field": "prompt", "error": "is required"}]}))
        with self.assertRaises(ApiError) as ctx:
            self.client.create_prediction("m", {})
        self.assertEqual(ctx.exception.message, "Invalid request: prompt: is required (HTTP 400)")

    def test_details_string_on_402(self):
        self.server.route("POST", "/v1/prediction", (402, {}, {
            "status": 402, "error": "Payment required", "details": "Balance is below $0.50"}))
        with self.assertRaises(ApiError) as ctx:
            self.client.create_prediction("m", {})
        self.assertIn("Balance is below $0.50", ctx.exception.message)

    def test_plain_error_and_non_json(self):
        self.server.route("GET", "/v1/prediction/x", (404, {}, {"error": "execution not found"}))
        with self.assertRaises(ApiError) as ctx:
            self.client.get_prediction("x")
        self.assertEqual(ctx.exception.message, "execution not found (HTTP 404)")
        self.server.route("GET", "/v1/prediction/y", (502, {"Content-Type": "text/plain"}, b"Bad gateway"))
        with self.assertRaises(ApiError) as ctx:
            self.client.get_prediction("y")
        self.assertIn("Bad gateway", ctx.exception.message)
        self.assertTrue(ctx.exception.transient)

    def test_html_error_page_becomes_a_sentence(self):
        page = (b'<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN">\n<HTML><HEAD>'
                b"<TITLE>ERROR: The request could not be satisfied</TITLE></HEAD><BODY>"
                b"<H1>504 Gateway Timeout ERROR</H1></BODY></HTML>")
        self.server.route("GET", "/v1/prediction/z", (504, {"Content-Type": "text/html"}, page))
        with self.assertRaises(ApiError) as ctx:
            self.client.get_prediction("z")
        self.assertEqual(ctx.exception.message, "Eachlabs did not answer in time; try again (HTTP 504)")
        self.assertNotIn("<", ctx.exception.message)

    def test_empty_body_uses_status_sentence(self):
        self.server.route("POST", "/v1/prediction", (422, {}, b""))
        with self.assertRaises(ApiError) as ctx:
            self.client.create_prediction("m", {})
        self.assertEqual(ctx.exception.message, "The request could not be processed (HTTP 422)")

    def test_missing_key_fails_before_network(self):
        client = EachlabsClient("", base_url=self.server.url)
        with self.assertRaises(ApiError) as ctx:
            client.get_balance()
        self.assertIn("No API key", ctx.exception.message)
        self.assertEqual(self.server.requests, [])

    def test_network_error_is_transient(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        client = EachlabsClient(KEY, base_url="http://127.0.0.1:%d" % port)
        with self.assertRaises(ApiError) as ctx:
            client.get_balance()
        self.assertTrue(ctx.exception.message.startswith("Network error"))
        self.assertIsNone(ctx.exception.status)
        self.assertTrue(ctx.exception.transient)


    def test_body_read_errors_become_api_errors(self):
        import http.client

        class Broken:
            def __init__(self, exc):
                self.exc = exc

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                raise self.exc

        for exc in (TimeoutError("timed out"), ConnectionResetError("reset"),
                    http.client.IncompleteRead(b"{", 10)):
            with mock.patch.object(self.client._opener, "open", return_value=Broken(exc)):
                with self.assertRaises(ApiError) as ctx:
                    self.client.chat_completion("m", [], [])
            self.assertTrue(ctx.exception.message.startswith("Network error: "), ctx.exception.message)
            self.assertIsNone(ctx.exception.status)

    def test_empty_tools_are_left_out_of_the_body(self):
        with mock.patch.object(self.client, "_json", return_value={}) as sent:
            self.client.chat_completion("m", [{"role": "user", "content": "x"}], [])
            self.client.chat_completion("m", [], [{"type": "function"}])
        self.assertNotIn("tools", sent.call_args_list[0].kwargs["body"])
        self.assertEqual(sent.call_args_list[1].kwargs["body"]["tools"], [{"type": "function"}])

    def test_bare_timeout_names_its_type(self):
        for where in ("open", "read"):
            exc = TimeoutError()
            if where == "open":
                patch = mock.patch.object(self.client._opener, "open", side_effect=exc)
            else:
                body = mock.MagicMock()
                body.__enter__.return_value.read.side_effect = exc
                patch = mock.patch.object(self.client._opener, "open", return_value=body)
            with patch:
                with self.assertRaises(ApiError) as ctx:
                    self.client.chat_completion("m", [], [])
            self.assertEqual(ctx.exception.message, "Network error: TimeoutError", where)


class PredictionTest(ClientTestCase):
    def test_create_sends_model_and_input_only(self):
        self.server.route("POST", "/v1/prediction",
                          (200, {}, {"status": "success", "message": "ok", "predictionID": "p-1"}))
        self.assertEqual(self.client.create_prediction("demo", {"prompt": "x"}), "p-1")
        request = self.server.find("POST", "/v1/prediction")[0]
        self.assertEqual(request.json(), {"model": "demo", "input": {"prompt": "x"}})
        self.assertEqual(request.headers["content-type"], "application/json")
        self.assertEqual(request.headers["authorization"], "Bearer " + KEY)

    def test_cancel(self):
        self.server.route("POST", "/v1/prediction/p-1/cancel", (200, {}, {"status": "success"}))
        self.assertEqual(self.client.cancel_prediction("p-1")["status"], "success")

    def test_trigger_workflow(self):
        self.server.route("POST", "/v1/workflows/trigger/wf/v2", (202, {}, {"execution_id": "e-1", "status": "queued"}))
        self.assertEqual(self.client.trigger_workflow("wf", "v2", {"shot": "u"}), "e-1")
        self.assertEqual(self.server.find("POST", "/v1/workflows/trigger/wf/v2")[0].json(), {"inputs": {"shot": "u"}})
        self.server.route("GET", "/v1/workflows/executions/e-1", (200, {}, {"status": "running"}))
        self.assertEqual(self.client.get_execution("e-1")["status"], "running")

    def test_create_workflow(self):
        created = {"workflow_id": "wf-9", "name": "Blender 3D model", "versions": [{"version_id": "v1"}]}
        self.server.route("POST", "/v1/workflows", (201, {}, created))
        definition = {"steps": [{"id": "a", "type": "model", "model": "m", "params": {}}]}
        result = self.client.create_workflow("Blender 3D model", definition)
        self.assertEqual(result["workflow_id"], "wf-9")
        request = self.server.find("POST", "/v1/workflows")[0]
        self.assertEqual(request.json(), {"name": "Blender 3D model", "definition": definition,
                                          "visibility": "private"})
        self.assertEqual(request.headers["authorization"], "Bearer " + KEY)

    def test_create_workflow_without_an_id_is_an_error(self):
        self.server.route("POST", "/v1/workflows", (201, {}, {"name": "x"}))
        with self.assertRaises(ApiError):
            self.client.create_workflow("x", {}, visibility="public")
        self.assertEqual(self.server.find("POST", "/v1/workflows")[0].json()["visibility"], "public")

    def test_put_workflow_version(self):
        self.server.route("PUT", "/v1/workflows/wf%2F1/versions/v3",
                          (200, {}, {"version_id": "v3", "published": True}))
        result = self.client.put_workflow_version("wf/1", "v3", {"steps": []})
        self.assertEqual(result["version_id"], "v3")
        request = self.server.find("PUT", "/v1/workflows/wf%2F1/versions/v3")[0]
        self.assertEqual(request.json(), {"definition": {"steps": []}, "published": True})
        self.client.put_workflow_version("wf/1", "v3", {"steps": []}, published=False)
        self.assertFalse(self.server.find("PUT", "/v1/workflows/wf%2F1/versions/v3")[1].json()["published"])

    def test_put_workflow_version_404(self):
        with self.assertRaises(ApiError) as caught:
            self.client.put_workflow_version("gone", "v2", {})
        self.assertEqual(caught.exception.status, 404)


class UploadTest(ClientTestCase):
    def write(self, name, data):
        path = os.path.join(self.tmp.name, name)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def test_presign_then_put_with_required_headers_and_no_key(self):
        upload_url = self.server.url + "/storage/upload?X-Amz-Signature=abc"
        self.server.route("POST", "/v1/upload/presign", (200, {}, {
            "id": "f-1", "presigned_url": upload_url, "public_url": "https://cdn.example/f-1.png",
            "required_headers": {"x-amz-meta-file-id": "f-1"}}))
        self.server.route("PUT", "/storage/upload", (200, {}, b""))
        path = self.write("still.png", b"\x89PNG fake bytes")
        url = self.client.upload_file(path, "image/png", "image")
        self.assertEqual(url, "https://cdn.example/f-1.png")
        presign = self.server.find("POST", "/v1/upload/presign")[0]
        self.assertEqual(presign.json(), {"content_type": "image/png", "file_type": "image",
                                          "expires_in_seconds": api_client.UPLOAD_RETENTION_SECONDS})
        put = self.server.find("PUT", "/storage/upload")[0]
        self.assertEqual(put.body, b"\x89PNG fake bytes")
        self.assertEqual(put.headers["content-type"], "image/png")
        self.assertEqual(put.headers["x-amz-meta-file-id"], "f-1")
        self.assertNotIn("authorization", put.headers)

    def test_storage_rejection_surfaces(self):
        self.server.route("POST", "/v1/upload/presign", (200, {}, {
            "presigned_url": self.server.url + "/storage/upload", "public_url": "https://cdn/x"}))
        self.server.route("PUT", "/storage/upload", (403, {"Content-Type": "application/xml"},
                                                     b"<Error><Code>SignatureDoesNotMatch</Code></Error>"))
        with self.assertRaises(ApiError) as ctx:
            self.client.upload_file(self.write("a.png", b"x"), "image/png", "image")
        self.assertIn("SignatureDoesNotMatch", ctx.exception.message)

    def test_too_large_is_refused_locally(self):
        path = self.write("big.mp4", b"x" * 20)
        with mock.patch.object(api_client, "MAX_UPLOAD_BYTES", 10):
            with self.assertRaises(ApiError) as ctx:
                self.client.upload_file(path, "video/mp4", "video")
        self.assertIn("100 MB", ctx.exception.message)
        self.assertEqual(self.server.requests, [])

    def test_cancel_before_upload(self):
        event = threading.Event()
        event.set()
        with self.assertRaises(api_client.Cancelled):
            self.client.upload_file(self.write("a.png", b"x"), "image/png", "image", cancel_event=event)


class DownloadTest(ClientTestCase):
    def test_streams_to_file_without_key(self):
        self.server.route("GET", "/out/result", (200, {"Content-Type": "video/mp4"}, b"\x00" * 3000000))
        dest = os.path.join(self.tmp.name, "r.download")
        content_type = self.client.download(self.server.url + "/out/result", dest)
        self.assertEqual(content_type, "video/mp4")
        self.assertEqual(os.path.getsize(dest), 3000000)
        self.assertNotIn("authorization", self.server.find("GET", "/out/result")[0].headers)

    def test_cancel_removes_partial_file(self):
        self.server.route("GET", "/out/result", (200, {}, b"\x00" * 10))
        event = threading.Event()
        event.set()
        dest = os.path.join(self.tmp.name, "r.download")
        with self.assertRaises(api_client.Cancelled):
            self.client.download(self.server.url + "/out/result", dest, cancel_event=event)
        self.assertEqual(os.listdir(self.tmp.name), [])

    def test_a_stop_during_a_download_ends_it_at_the_next_chunk(self):
        self.server.route("GET", "/out/result", (200, {}, b"\x00" * (api_client.CHUNK * 8)))

        class StopAfterFirstChunk:
            checks = 0

            def is_set(self):
                self.checks += 1
                return self.checks > 2

        dest = os.path.join(self.tmp.name, "r.download")
        with self.assertRaises(api_client.Cancelled):
            self.client.download(self.server.url + "/out/result", dest, cancel_event=StopAfterFirstChunk())
        self.assertEqual(os.listdir(self.tmp.name), [])
        self.assertLessEqual(api_client.CHUNK, 64 * 1024)
        self.assertLessEqual(api_client.READ_TIMEOUT, 30)

    def test_a_download_past_its_wait_limit_fails_and_leaves_no_file(self):
        self.server.route("GET", "/out/result", (200, {}, b"\x00" * (api_client.CHUNK * 4)))
        dest = os.path.join(self.tmp.name, "r.download")
        clock = iter([0.0, 5.0, 11.0, 12.0, 13.0, 14.0])
        with mock.patch.object(api_client.time, "monotonic", lambda: next(clock)):
            with self.assertRaises(ApiError) as caught:
                self.client.download(self.server.url + "/out/result", dest, wait_seconds=10)
        self.assertEqual(caught.exception.message, "The download took longer than 10 seconds")
        self.assertEqual(os.listdir(self.tmp.name), [])

    def test_a_download_has_no_wait_limit_unless_one_is_given(self):
        self.server.route("GET", "/out/result", (200, {}, b"\x00" * 1000))
        dest = os.path.join(self.tmp.name, "r.download")
        self.client.download(self.server.url + "/out/result", dest)
        self.assertEqual(os.path.getsize(dest), 1000)
        self.assertEqual(api_client.DOWNLOAD_TIMEOUT, 120)

    def test_a_download_over_its_cap_stops_while_streaming(self):
        self.server.route("GET", "/out/result", (200, {}, b"\x00" * 300000))
        dest = os.path.join(self.tmp.name, "r.download")
        with self.assertRaises(ApiError) as caught:
            self.client.download(self.server.url + "/out/result", dest, max_bytes=100000)
        self.assertIn("larger than", caught.exception.message)
        self.assertEqual(os.listdir(self.tmp.name), [])

    def test_a_redirect_to_plain_http_is_refused(self):
        self.server.route("GET", "/out/moved", (302, {"Location": "http://cdn.example/x.png"}, b""))
        dest = os.path.join(self.tmp.name, "r.download")
        with self.assertRaises(ApiError) as caught:
            self.client.download(self.server.url + "/out/moved", dest)
        self.assertIn("redirect", caught.exception.message)
        self.assertEqual(os.listdir(self.tmp.name), [])
        handler = api_client._SecureRedirects()
        request = urllib.request.Request("https://files.example/m.zip")
        with self.assertRaises(ApiError):  # https never becomes http, not even to this computer
            handler.redirect_request(request, None, 302, "Found", {}, "http://127.0.0.1/m.zip")
        self.assertIsNotNone(handler.redirect_request(request, None, 302, "Found", {}, "https://cdn.example/m.zip"))

    def test_a_redirect_that_stays_secure_is_followed(self):
        self.server.route("GET", "/out/moved", (302, {"Location": "/out/result"}, b""))
        self.server.route("GET", "/out/result", (200, {}, b"\x00" * 10))
        dest = os.path.join(self.tmp.name, "r.download")
        self.client.download(self.server.url + "/out/moved", dest)
        self.assertEqual(os.path.getsize(dest), 10)

    def test_refuses_plain_http_results(self):
        with self.assertRaises(ApiError):
            self.client.download("http://cdn.example/x.png", os.path.join(self.tmp.name, "x"))


class HelperTest(unittest.TestCase):
    def test_validate_base_url(self):
        self.assertEqual(api_client.validate_base_url("https://api.eachlabs.ai/"), "https://api.eachlabs.ai")
        self.assertEqual(api_client.validate_base_url(" https://api.example.com "), "https://api.example.com")
        self.assertEqual(api_client.validate_base_url("http://127.0.0.1:8080"), "http://127.0.0.1:8080")
        for bad in ("http://api.eachlabs.ai", "ftp://x", "api.eachlabs.ai", ""):
            with self.assertRaises(ValueError):
                api_client.validate_base_url(bad)

    def test_normalize_status(self):
        expected = {
            "created": "QUEUED", "starting": "QUEUED", "queued": "QUEUED",
            "processing": "RUNNING", "running": "RUNNING",
            "success": "SUCCEEDED", "completed": "SUCCEEDED",
            "error": "FAILED", "failed": "FAILED",
            "cancelled": "CANCELLED", "canceled": "CANCELLED",
            "something-new": "RUNNING", None: "RUNNING",
        }
        for raw, status in expected.items():
            self.assertEqual(api_client.normalize_status(raw), status, raw)

    def test_output_urls(self):
        self.assertEqual(api_client.output_urls("https://cdn/a.mp4"), ["https://cdn/a.mp4"])
        self.assertEqual(api_client.output_urls(["https://cdn/a.png", "https://cdn/b.png", "https://cdn/a.png"]),
                         ["https://cdn/a.png", "https://cdn/b.png"])
        self.assertEqual(api_client.output_urls({"video": {"url": "https://cdn/v.mp4"}, "seed": 3, "note": "text"}),
                         ["https://cdn/v.mp4"])
        self.assertEqual(api_client.output_urls(None), [])


if __name__ == "__main__":
    unittest.main()
