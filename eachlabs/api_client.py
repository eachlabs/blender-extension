"""Eachlabs HTTPS API client. Standard library only, no ``bpy``; safe to use from worker threads.

Endpoints and response shapes follow the public API reference at https://docs.eachlabs.ai.
"""

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE_URL = "https://api.eachlabs.ai"
DEFAULT_TIMEOUT = 30
DOWNLOAD_TIMEOUT = 120
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 4 * 1024 * 1024 * 1024
UPLOAD_RETENTION_SECONDS = 7 * 24 * 3600
CHUNK = 1024 * 1024

QUEUED = "QUEUED"
RUNNING = "RUNNING"
SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"
CANCELLED = "CANCELLED"
TERMINAL = frozenset((SUCCEEDED, FAILED, CANCELLED))

_STATUS = {
    "created": QUEUED,
    "queued": QUEUED,
    "pending": QUEUED,
    "starting": QUEUED,
    "processing": RUNNING,
    "running": RUNNING,
    "in_progress": RUNNING,
    "success": SUCCEEDED,
    "succeeded": SUCCEEDED,
    "completed": SUCCEEDED,
    "failed": FAILED,
    "error": FAILED,
    "cancelled": CANCELLED,
    "canceled": CANCELLED,
}


class ApiError(Exception):
    """An HTTP or network failure, carrying the API's own error text when it sent one."""

    def __init__(self, message, status=None, url=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.url = url

    @property
    def transient(self):
        return self.status is None or self.status == 429 or self.status >= 500


class Cancelled(Exception):
    """Raised inside transfers when the job's cancel event is set."""


def normalize_status(raw):
    """Map prediction and workflow statuses onto one lifecycle. Unknown values keep polling."""
    return _STATUS.get(str(raw or "").strip().lower(), RUNNING)


# Used when the API returns an empty body, which it does for auth failures and some prediction errors.
_STATUS_TEXT = {
    400: "The request was rejected; check the model inputs",
    401: "Invalid or missing API key",
    402: "Insufficient Eachlabs balance",
    403: "This API key is not allowed to do that",
    404: "Not found",
    409: "Conflict; the run may already be finished",
    422: "The request could not be processed",
    429: "Too many requests; try again shortly",
    502: "Eachlabs could not reach the model provider",
    503: "Eachlabs is temporarily unavailable",
}


def error_text(status, body):
    """Readable error line from an HTTP status and response body (bytes or str)."""
    if isinstance(body, bytes):
        body = body.decode("utf-8", "replace")
    body = (body or "").strip()
    message = ""
    if body:
        try:
            data = json.loads(body)
        except ValueError:
            data = None
        if isinstance(data, dict):
            message = _first_text(data, ("error", "message", "detail", "error_cause"))
            details = _details_text(data.get("details"))
            if details and details.lower() not in message.lower():
                message = "%s: %s" % (message, details) if message else details
        elif data is None:
            message = body[:300]
    if not message:
        message = _STATUS_TEXT.get(status, "Request failed")
    return "%s (HTTP %s)" % (message, status) if status else message


def _first_text(data, keys):
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = _first_text(value, ("message", "error", "detail"))
            if nested:
                return nested
    return ""


def _details_text(details):
    """Flatten ``details``: a string, or validation entries like ``[{"field": ..., "error": ...}]``."""
    if isinstance(details, str):
        return details.strip()
    if isinstance(details, dict):
        details = [details]
    if isinstance(details, list):
        parts = []
        for item in details[:3]:
            if isinstance(item, dict):
                field = item.get("field")
                text = item.get("error") or item.get("message") or ""
                parts.append("%s: %s" % (field, text) if field else str(text))
            elif item:
                parts.append(str(item))
        return "; ".join(p for p in parts if p)
    return ""


def output_urls(output):
    """Every http(s) URL in a prediction or workflow output, in order, without duplicates."""
    found = []

    def walk(value, depth):
        if depth > 5:
            return
        if isinstance(value, str):
            if value.startswith(("https://", "http://")):
                found.append(value)
        elif isinstance(value, list):
            for item in value:
                walk(item, depth + 1)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item, depth + 1)

    walk(output, 0)
    seen = set()
    return [u for u in found if not (u in seen or seen.add(u))]


def validate_base_url(base_url):
    """Return a normalized base URL or raise ``ValueError``. Plain HTTP is allowed only locally."""
    parsed = urllib.parse.urlparse((base_url or "").strip())
    if parsed.scheme not in ("https", "http") or not parsed.netloc:
        raise ValueError("API URL must look like https://api.eachlabs.ai")
    if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("API URL must use https")
    return "%s://%s%s" % (parsed.scheme, parsed.netloc, parsed.path.rstrip("/"))


def _ssl_context():
    context = ssl.create_default_context()
    try:
        import certifi  # Bundled with Blender's Python on some platforms.
    except ImportError:
        return context
    try:
        context.load_verify_locations(cafile=certifi.where())
    except (OSError, ssl.SSLError):
        pass
    return context


class EachlabsClient:
    def __init__(self, api_key, base_url=DEFAULT_BASE_URL, user_agent="eachlabs-blender", timeout=DEFAULT_TIMEOUT):
        self.api_key = (api_key or "").strip()
        self.base_url = validate_base_url(base_url)
        self.user_agent = user_agent
        self.timeout = timeout
        context = _ssl_context()
        self._opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))

    # -- transport ---------------------------------------------------------------------------

    def _url(self, path, query=None):
        url = self.base_url + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        return url

    def _open(self, request, timeout):
        try:
            return self._opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            body = b""
            try:
                body = exc.read()
            except OSError:
                pass
            finally:
                exc.close()
            raise ApiError(error_text(exc.code, body), status=exc.code, url=request.full_url) from None
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise ApiError("Network error: %s" % (reason,), url=request.full_url) from None
        except (TimeoutError, OSError) as exc:
            raise ApiError("Network error: %s" % (exc,), url=request.full_url) from None

    def _json(self, method, path, body=None, query=None, auth=True):
        headers = {"Accept": "application/json", "User-Agent": self.user_agent}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if auth:
            if not self.api_key:
                raise ApiError("No API key set. Add one in the Eachlabs add-on preferences.")
            headers["Authorization"] = "Bearer " + self.api_key
        request = urllib.request.Request(self._url(path, query), data=data, headers=headers, method=method)
        with self._open(request, self.timeout) as response:
            raw = response.read()
        if not raw.strip():
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            raise ApiError("Unexpected non-JSON response from %s" % path, url=request.full_url) from None

    # -- catalog -----------------------------------------------------------------------------

    def list_models(self, page_size=100, max_pages=50):
        """Every model in the catalog. The server caps pages at 200 regardless of ``limit``."""
        models, offset = [], 0
        for _ in range(max_pages):
            page = self._json("GET", "/v1/models", query={"limit": page_size, "offset": offset}, auth=False)
            if not isinstance(page, list):
                raise ApiError("Unexpected model list response")
            models.extend(page)
            if len(page) < page_size:
                break
            offset += len(page)
        return models

    def get_model(self, slug):
        return self._json("GET", "/v1/models/" + urllib.parse.quote(slug, safe=""), auth=False)

    def list_workflows(self, page_size=100, max_pages=20):
        workflows, offset = [], 0
        for _ in range(max_pages):
            page = self._json("GET", "/v1/workflows", query={"limit": page_size, "offset": offset})
            rows = page.get("workflows") or []
            workflows.extend(rows)
            if len(rows) < page_size or page.get("offset") is None:
                break
            offset = page["offset"]
        return workflows

    def get_workflow(self, workflow_id):
        return self._json("GET", "/v1/workflows/" + urllib.parse.quote(workflow_id, safe=""))

    def get_balance(self):
        return self._json("GET", "/v1/billing/balance")

    # -- uploads -----------------------------------------------------------------------------

    def presign_upload(self, content_type, file_type, expires_in_seconds=UPLOAD_RETENTION_SECONDS):
        body = {"content_type": content_type, "file_type": file_type}
        if expires_in_seconds:
            body["expires_in_seconds"] = int(expires_in_seconds)
        return self._json("POST", "/v1/upload/presign", body=body)

    def upload_file(self, path, content_type, file_type, cancel_event=None, expires_in_seconds=UPLOAD_RETENTION_SECONDS):
        """Upload a local file through a presigned URL and return its public URL."""
        size = os.path.getsize(path)
        if size > MAX_UPLOAD_BYTES:
            raise ApiError("%s is %.0f MB; uploads are limited to 100 MB. Lower the preview resolution "
                           "or shorten the range." % (os.path.basename(path), size / 1048576.0))
        _check(cancel_event)
        slot = self.presign_upload(content_type, file_type, expires_in_seconds)
        upload_url, public_url = slot.get("presigned_url"), slot.get("public_url")
        if not upload_url or not public_url:
            raise ApiError("Upload slot response is missing presigned_url or public_url")
        _check(cancel_event)
        # The presigned URL is signed for these exact headers. No Authorization header goes to storage.
        headers = {"Content-Type": content_type, "Content-Length": str(size), "User-Agent": self.user_agent}
        headers.update({str(k): str(v) for k, v in (slot.get("required_headers") or {}).items()})
        with open(path, "rb") as handle:
            request = urllib.request.Request(upload_url, data=handle, headers=headers, method="PUT")
            with self._open(request, DOWNLOAD_TIMEOUT) as response:
                response.read()
        return public_url

    # -- predictions -------------------------------------------------------------------------

    def create_prediction(self, model, input_values):
        result = self._json("POST", "/v1/prediction", body={"model": model, "input": input_values})
        prediction_id = result.get("predictionID") or result.get("prediction_id") or result.get("id")
        if not prediction_id:
            raise ApiError(error_text(None, json.dumps(result)) if result else "Prediction was not created")
        return prediction_id

    def get_prediction(self, prediction_id):
        return self._json("GET", "/v1/prediction/" + urllib.parse.quote(prediction_id, safe=""))

    def cancel_prediction(self, prediction_id):
        return self._json("POST", "/v1/prediction/%s/cancel" % urllib.parse.quote(prediction_id, safe=""))

    # -- workflows ---------------------------------------------------------------------------

    def trigger_workflow(self, workflow_id, version_id, inputs):
        path = "/v1/workflows/trigger/%s/%s" % (
            urllib.parse.quote(workflow_id, safe=""), urllib.parse.quote(version_id, safe=""))
        result = self._json("POST", path, body={"inputs": inputs})
        execution_id = result.get("execution_id") or result.get("id")
        if not execution_id:
            raise ApiError("Workflow was not triggered")
        return execution_id

    def get_execution(self, execution_id):
        return self._json("GET", "/v1/workflows/executions/" + urllib.parse.quote(execution_id, safe=""))

    # -- downloads ---------------------------------------------------------------------------

    def download(self, url, dest_path, cancel_event=None, max_bytes=MAX_DOWNLOAD_BYTES):
        """Stream ``url`` to ``dest_path``; return the response content type. Sends no API key."""
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ApiError("Refusing to download a non-https result URL")
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        partial = dest_path + ".part"
        total = 0
        try:
            with self._open(request, DOWNLOAD_TIMEOUT) as response, open(partial, "wb") as out:
                content_type = response.headers.get("Content-Type", "")
                while True:
                    _check(cancel_event)
                    chunk = response.read(CHUNK)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise ApiError("Result is larger than %d MB" % (max_bytes // 1048576))
                    out.write(chunk)
            os.replace(partial, dest_path)
        finally:
            if os.path.exists(partial):
                os.remove(partial)
        return content_type


def _check(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise Cancelled()
