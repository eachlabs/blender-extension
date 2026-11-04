"""Minimal MCP client over streamable HTTP. Standard library only, no ``bpy``; safe in worker threads.

Covers what the add-on needs: ``initialize`` and ``tools/list``. Replies may be plain JSON or a
server-sent event stream; both are read to the reply that carries the request's id.
"""

import json
import os
import urllib.error
import urllib.request

from .api_client import ApiError, _ssl_context, error_text, validate_base_url

DEFAULT_API_URL = "https://api.eachlabs.ai"
DEFAULT_MCP_URL = "https://mcp.eachlabs.ai/mcp"
PROTOCOL_VERSION = "2025-06-18"
MAX_TOOL_PAGES = 20


def mcp_url(base_url, override):
    """MCP address for an API address: the default pair, else the override, else ``None``."""
    try:
        base = validate_base_url(base_url)
    except ValueError:
        return None
    if base == DEFAULT_API_URL:
        return DEFAULT_MCP_URL
    try:
        return validate_base_url(override)
    except ValueError:
        return None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: urllib would copy the Authorization header to the new address."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class McpClient:
    def __init__(self, url, api_key, user_agent="eachlabs-blender", timeout=20.0):
        self.url = url
        self.api_key = (api_key or "").strip()
        self.user_agent = user_agent
        self.timeout = timeout
        self.session_id = None
        self._next_id = 1
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=_ssl_context()), _NoRedirect)

    def initialize(self):
        """Open the session and return the server's info."""
        result = self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": self.user_agent, "version": "1"},
        })
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return result.get("serverInfo") or {}

    def list_tools(self):
        tools, cursor = [], None
        for _ in range(MAX_TOOL_PAGES):
            result = self._request("tools/list", {"cursor": cursor} if cursor else None)
            tools.extend(result.get("tools") or [])
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools

    # -- transport ---------------------------------------------------------------------------

    def _request(self, method, params=None):
        request_id = self._next_id
        self._next_id += 1
        message = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        reply = self._post(message, request_id)
        if reply is None:
            raise ApiError("MCP server sent no reply to %s" % method, url=self.url)
        if reply.get("error"):
            error = reply["error"]
            text = error.get("message") if isinstance(error, dict) else str(error)
            raise ApiError("MCP error: %s" % (text or "request failed"), url=self.url)
        result = reply.get("result")
        return result if isinstance(result, dict) else {}

    def _post(self, message, request_id=None):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": self.user_agent,
            "Authorization": "Bearer " + self.api_key,
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        request = urllib.request.Request(
            self.url, data=json.dumps(message).encode("utf-8"), headers=headers, method="POST")
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                session = response.headers.get("Mcp-Session-Id")
                content_type = response.headers.get("Content-Type", "")
                raw = response.read()
        except urllib.error.HTTPError as exc:
            body = b""
            try:
                body = exc.read()
            except OSError:
                pass
            finally:
                exc.close()
            if 300 <= exc.code < 400:
                raise ApiError("The MCP address redirects elsewhere (HTTP %s); check EACHLABS_MCP_URL."
                               % exc.code, status=exc.code, url=self.url) from None
            raise ApiError(error_text(exc.code, body), status=exc.code, url=self.url) from None
        except urllib.error.URLError as exc:
            raise ApiError("Network error: %s" % (getattr(exc, "reason", exc),), url=self.url) from None
        except OSError as exc:
            raise ApiError("Network error: %s" % (exc,), url=self.url) from None
        if session and not self.session_id:
            self.session_id = session
        if request_id is None or not raw.strip():
            return None
        return _find_reply(raw.decode("utf-8", "replace"), content_type, request_id, self.url)


def _find_reply(text, content_type, request_id, url):
    if "text/event-stream" in content_type:
        candidates = []
        for event in text.replace("\r\n", "\n").split("\n\n"):
            data = "\n".join(line[5:].lstrip(" ") for line in event.split("\n") if line.startswith("data:"))
            if data.strip():
                candidates.append(data)
    else:
        candidates = [text]
    for data in candidates:
        try:
            parsed = json.loads(data)
        except ValueError:
            continue
        for item in parsed if isinstance(parsed, list) else [parsed]:
            if isinstance(item, dict) and item.get("id") == request_id and ("result" in item or "error" in item):
                return item
    raise ApiError("Unexpected reply from the MCP server", url=url)


def check(base_url, api_key):
    """Try the MCP connection. Returns ``(True, "MCP connected")`` or ``(False, one line)``."""
    url = mcp_url(base_url, os.environ.get("EACHLABS_MCP_URL"))
    if not url:
        return False, "Set EACHLABS_MCP_URL to the MCP address for this API URL."
    try:
        client = McpClient(url, api_key)
        client.initialize()
        client.list_tools()
    except ApiError as exc:
        if exc.status == 401:
            return False, "API key was rejected (HTTP 401)."
        return False, " ".join(exc.message.split())
    return True, "MCP connected"
