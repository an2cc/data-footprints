# SPDX-FileCopyrightText: 2026 Anna Caellas-Camprubí
# SPDX-License-Identifier: EUPL-1.2

"""Authenticated Alien OpenAIRE MCP provider for Data Footprints.

The remote MCP server uses OAuth 2.0 / OpenID Connect.  This module relies on
MCP Python SDK's OAuthClientProvider, which performs protected-resource and
authorization-server discovery, dynamic client registration, PKCE, token
refresh and bearer-token injection.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Awaitable, Iterable, TypeVar
from urllib.parse import parse_qs, urlparse

DEFAULT_MCP_URL = os.getenv("ALIEN_MCP_URL", "https://openaire.mcp.alien.club/mcp").rstrip("/")
OPENAIRE_GRAPH_LINKS_URL = os.getenv(
    "OPENAIRE_GRAPH_LINKS_URL",
    "https://api.openaire.eu/graph/v3/research-products/links",
).strip()
OAUTH_CALLBACK_HOST = "127.0.0.1"
OAUTH_CALLBACK_PORT = int(os.getenv("ALIEN_OAUTH_CALLBACK_PORT", "8765"))
OAUTH_CALLBACK_PATH = "/callback"
OAUTH_REDIRECT_URI = f"http://{OAUTH_CALLBACK_HOST}:{OAUTH_CALLBACK_PORT}{OAUTH_CALLBACK_PATH}"
OAUTH_SCOPE = "openid profile email offline_access"
T = TypeVar("T")


def _auth_file() -> Path:
    """Return a per-user token/client-registration file outside the project."""
    override = os.getenv("ALIEN_OAUTH_STORAGE", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".data_footprints" / "alien_openaire_oauth.json"


class ProviderError(RuntimeError):
    """Raised when a live MCP request cannot be completed."""


class OAuthLoginError(ProviderError):
    """Raised when the interactive OAuth login cannot be completed."""


def oauth_state_exists() -> bool:
    """Whether local OAuth client information or tokens have been stored."""
    path = _auth_file()
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(payload.get("tokens") or payload.get("client_info"))


def clear_oauth_state() -> None:
    """Delete locally stored OAuth tokens and dynamic client registration."""
    path = _auth_file()
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise ProviderError(f"Could not remove the local OAuth credentials at {path}: {exc}") from exc


class FileTokenStorage:
    """Minimal persistent TokenStorage implementation for the MCP SDK."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _auth_file()
        self._lock = threading.Lock()

    def _read(self) -> dict[str, Any]:
        with self._lock:
            if not self.path.exists():
                return {}
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
            return value if isinstance(value, dict) else {}

    def _write(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.path)
            try:
                self.path.chmod(0o600)
            except OSError:
                # Windows ACLs are not controlled fully by POSIX chmod.
                pass

    async def get_tokens(self):
        from mcp.shared.auth import OAuthToken

        value = self._read().get("tokens")
        if not isinstance(value, dict):
            return None
        try:
            return OAuthToken.model_validate(value)
        except Exception:
            return None

    async def set_tokens(self, tokens) -> None:
        payload = self._read()
        payload["tokens"] = tokens.model_dump(mode="json", exclude_none=True)
        payload["updated_at"] = int(time.time())
        self._write(payload)

    async def get_client_info(self):
        from mcp.shared.auth import OAuthClientInformationFull

        value = self._read().get("client_info")
        if not isinstance(value, dict):
            return None
        try:
            return OAuthClientInformationFull.model_validate(value)
        except Exception:
            return None

    async def set_client_info(self, client_info) -> None:
        payload = self._read()
        payload["client_info"] = client_info.model_dump(mode="json", exclude_none=True)
        payload["updated_at"] = int(time.time())
        self._write(payload)


class LocalOAuthCallback:
    """Small loopback HTTP receiver for the OAuth authorization response."""

    def __init__(self, host: str = OAUTH_CALLBACK_HOST, port: int = OAUTH_CALLBACK_PORT) -> None:
        self.host = host
        self.port = port
        self._result: Queue[tuple[str | None, str | None, str | None]] = Queue(maxsize=1)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._server is not None:
            return
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
                parsed = urlparse(self.path)
                query = parse_qs(parsed.query)
                code = query.get("code", [None])[0]
                state = query.get("state", [None])[0]
                error = query.get("error_description", query.get("error", [None]))[0]
                try:
                    receiver._result.put_nowait((code, state, error))
                except Exception:
                    pass

                success = bool(code) and not error
                title = "Data Footprints is connected" if success else "Authorization was not completed"
                body = (
                    "You can close this tab and return to the Data Footprints application."
                    if success
                    else f"The Alien authorization response did not include a usable code. {error or ''}"
                )
                html = f"""<!doctype html><html><head><meta charset='utf-8'><title>{title}</title>
                <style>body{{font-family:Segoe UI,Arial,sans-serif;background:#f5f7fb;color:#1f2937;
                display:grid;place-items:center;min-height:90vh}}main{{max-width:620px;background:white;border:1px solid #e5e7eb;
                border-radius:16px;padding:32px;box-shadow:0 8px 30px rgba(16,24,40,.08)}}h1{{font-size:24px}}</style>
                </head><body><main><h1>{title}</h1><p>{body}</p></main></body></html>"""
                encoded = html.encode("utf-8")
                self.send_response(200 if success else 400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                return

        try:
            self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        except OSError as exc:
            raise OAuthLoginError(
                f"Could not open the local OAuth callback at {OAUTH_REDIRECT_URI}. "
                f"Close any other Data Footprints process and retry. Technical detail: {exc}"
            ) from exc
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    async def open_browser(self, authorization_url: str) -> None:
        self.start()
        print("\nOpen this URL to connect Data Footprints to Alien OpenAIRE:\n")
        print(authorization_url)
        print()
        opened = await asyncio.to_thread(webbrowser.open, authorization_url, 2)
        if not opened:
            print("The browser could not be opened automatically. Copy the URL above into a browser.")

    async def wait_for_callback(self, timeout: float = 300.0) -> tuple[str, str | None]:
        self.start()
        try:
            code, state, error = await asyncio.to_thread(self._result.get, True, timeout)
        except Empty as exc:
            raise OAuthLoginError(
                "The Alien login was not completed within five minutes. Click Build map and try again."
            ) from exc
        finally:
            self.stop()
        if error:
            raise OAuthLoginError(f"Alien authorization was rejected: {error}")
        if not code:
            raise OAuthLoginError("Alien returned no authorization code.")
        return code, state


def _exception_details(exc: BaseException) -> str:
    """Return useful details from nested ExceptionGroup/TaskGroup failures."""
    parts: list[str] = []
    seen: set[int] = set()

    def visit(error: BaseException, depth: int = 0) -> None:
        if id(error) in seen or depth > 8:
            return
        seen.add(id(error))
        nested = getattr(error, "exceptions", None)
        if nested and isinstance(nested, (list, tuple)):
            for child in nested:
                if isinstance(child, BaseException):
                    visit(child, depth + 1)
            return
        label = error.__class__.__name__
        message = str(error).strip()
        response = getattr(error, "response", None)
        if response is not None:
            status = getattr(response, "status_code", None)
            reason = getattr(response, "reason_phrase", None)
            url = getattr(response, "url", None)
            body = ""
            try:
                body = (getattr(response, "text", "") or "").strip().replace("\n", " ")[:600]
            except Exception:
                body = ""
            bits = [str(status) if status is not None else "HTTP error"]
            if reason:
                bits.append(str(reason))
            if url:
                bits.append(str(url))
            message = " · ".join(bits) + (f" · {body}" if body else "")
        entry = f"{label}: {message}" if message else label
        if entry not in parts:
            parts.append(entry)
        cause = getattr(error, "__cause__", None)
        context = getattr(error, "__context__", None)
        if isinstance(cause, BaseException):
            visit(cause, depth + 1)
        elif isinstance(context, BaseException):
            visit(context, depth + 1)

    visit(exc)
    return " | ".join(parts) or repr(exc)


def _diagnostic_hint(detail: str) -> str:
    lower = detail.lower()
    if "401" in lower or "unauthorized" in lower or "invalid_token" in lower:
        return " Clear the saved Alien login in the connection controls and reconnect."
    if "403" in lower or "forbidden" in lower:
        return " The signed-in Alien account does not have permission to use this MCP resource."
    if "name or service not known" in lower or "nameresolution" in lower or "dns" in lower:
        return " The computer could not resolve the MCP host; check DNS, VPN or firewall settings."
    if "certificate_verify_failed" in lower or ("ssl" in lower and "certificate" in lower):
        return (
            " TLS certificate validation failed, often because a corporate or university proxy intercepts HTTPS. "
            "Try another network or install the organisation's trusted certificate."
        )
    if "connecttimeout" in lower or "readtimeout" in lower or "timed out" in lower:
        return " The MCP server or an upstream OpenAIRE service timed out; retry."
    if "404" in lower or "not found" in lower:
        return " Verify that ALIEN_MCP_URL is https://openaire.mcp.alien.club/mcp."
    if "tool" in lower and ("not found" in lower or "unknown" in lower):
        return " The connected MCP profile does not currently expose the requested OpenAIRE tool."
    if "registration" in lower:
        return " Dynamic client registration failed; clear the saved login and retry."
    return ""


def _run_async(awaitable: Awaitable[T]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, awaitable).result()


def _decode_json_layers(value: Any) -> Any:
    current = value
    for _ in range(5):
        if isinstance(current, str):
            text = current.strip()
            if not text:
                return {}
            try:
                current = json.loads(text)
                continue
            except json.JSONDecodeError:
                return current
        if isinstance(current, dict) and set(current) == {"result"}:
            current = current["result"]
            continue
        break
    return current


@dataclass(slots=True)
class OpenAIREProvider:
    """Synchronous wrapper around Alien's authenticated OpenAIRE MCP tools."""

    mcp_url: str = DEFAULT_MCP_URL
    timeout: int = 90

    async def _call_tool_async(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            import httpx
            from mcp import ClientSession
            from mcp.client.auth import OAuthClientProvider
            from mcp.client.streamable_http import streamable_http_client
            from mcp.shared.auth import OAuthClientMetadata
        except ImportError as exc:
            raise ProviderError(
                'The MCP OAuth client is not installed. Run: pip install -r requirements.txt'
            ) from exc

        manual_token = os.getenv("ALIEN_MCP_TOKEN", "").strip()
        headers: dict[str, str] = {}
        auth = None
        callback: LocalOAuthCallback | None = None
        if manual_token:
            # Optional compatibility path for tokens explicitly supplied by organisers.
            headers["Authorization"] = f"Bearer {manual_token}"
        else:
            callback = LocalOAuthCallback()
            client_metadata = OAuthClientMetadata(
                redirect_uris=[OAUTH_REDIRECT_URI],
                token_endpoint_auth_method="client_secret_post",
                grant_types=["authorization_code", "refresh_token"],
                response_types=["code"],
                scope=OAUTH_SCOPE,
                client_name="Data Footprints",
                software_id="data-footprints",
                software_version="1.0.0",
            )
            auth = OAuthClientProvider(
                server_url=self.mcp_url,
                client_metadata=client_metadata,
                storage=FileTokenStorage(),
                redirect_handler=callback.open_browser,
                callback_handler=callback.wait_for_callback,
                timeout=300.0,
            )

        timeout = httpx.Timeout(self.timeout, connect=min(self.timeout, 30), read=max(self.timeout, 150))
        try:
            async with httpx.AsyncClient(
                headers=headers,
                auth=auth,
                timeout=timeout,
                follow_redirects=True,
                http2=False,
            ) as client:
                async with streamable_http_client(
                    self.mcp_url,
                    http_client=client,
                    terminate_on_close=False,
                ) as (read_stream, write_stream, _):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        available = await session.list_tools()
                        available_names = {tool.name for tool in available.tools}
                        if tool_name not in available_names:
                            preview = ", ".join(sorted(available_names)[:20]) or "none"
                            raise ProviderError(
                                f"MCP connected, but tool {tool_name!r} is not exposed. "
                                f"Available tools include: {preview}"
                            )
                        result = await session.call_tool(tool_name, arguments=arguments)
        except (ProviderError, OAuthLoginError):
            raise
        except BaseException as exc:
            detail = _exception_details(exc)
            hint = _diagnostic_hint(detail)
            raise ProviderError(
                f"Alien OpenAIRE MCP request failed while calling {tool_name}: {detail}.{hint}"
            ) from exc
        finally:
            if callback is not None:
                callback.stop()

        if getattr(result, "isError", False) or getattr(result, "is_error", False):
            messages = [
                str(getattr(block, "text", ""))
                for block in getattr(result, "content", [])
                if getattr(block, "text", None)
            ]
            raise ProviderError(
                f"MCP tool {tool_name} returned an error: " + (" ".join(messages) or "Unknown tool error")
            )

        structured = getattr(result, "structuredContent", None)
        if structured is None:
            structured = getattr(result, "structured_content", None)
        if structured:
            decoded = _decode_json_layers(structured)
            if isinstance(decoded, dict):
                return decoded
        for block in getattr(result, "content", []):
            text = getattr(block, "text", None)
            if text:
                decoded = _decode_json_layers(text)
                if isinstance(decoded, dict):
                    return decoded
        raise ProviderError(f"MCP tool {tool_name} returned no readable JSON payload.")

    def _call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return _run_async(self._call_tool_async(tool_name, arguments))

    @staticmethod
    def _extract_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
        decoded = _decode_json_layers(payload)
        if not isinstance(decoded, dict):
            return []
        data = decoded.get("data", decoded)
        if isinstance(data, dict):
            for key in ("results", "datasets", "items", "links", "nodes"):
                if isinstance(data.get(key), list):
                    return [item for item in data[key] if isinstance(item, dict)]
        return []

    @staticmethod
    def _extract_record(payload: dict[str, Any]) -> dict[str, Any]:
        decoded = _decode_json_layers(payload)
        if not isinstance(decoded, dict):
            return {}
        data = decoded.get("data", decoded)
        if not isinstance(data, dict):
            return {}
        for key in ("result", "research_product", "product", "record"):
            if isinstance(data.get(key), dict):
                return data[key]
        return data

    @staticmethod
    def _record_identity(record: dict[str, Any]) -> str:
        return str(record.get("id") or record.get("doi") or record.get("title") or "").strip()

    def _search_research_product_pages(
        self,
        *,
        product_type: str,
        author_orcid: str | None = None,
        author_full_name: str | None = None,
        page_size: int = 100,
        max_pages: int = 100,
    ) -> tuple[list[dict[str, Any]], int]:
        """Retrieve and deduplicate all available MCP search pages."""
        safe_page_size = max(1, min(int(page_size), 100))
        combined: dict[str, dict[str, Any]] = {}
        page = 1
        pages_read = 0

        while page <= max_pages:
            arguments: dict[str, Any] = {
                "type": [product_type],
                "page": page,
                "page_size": safe_page_size,
                "detail": "full",
                "response_format": "json",
            }
            if author_orcid:
                arguments["author_orcid"] = [author_orcid]
            if author_full_name:
                arguments["author_full_name"] = [author_full_name]

            payload = self._call_tool("openaire_search_research_products", arguments)
            page_results = self._extract_results(payload)
            pages_read += 1

            before = len(combined)
            for record in page_results:
                key = self._record_identity(record)
                if key:
                    combined[key] = record
            added = len(combined) - before

            if not page_results or len(page_results) < safe_page_size or added == 0:
                break
            page += 1

        return list(combined.values()), pages_read

    def search_datasets_by_orcid_paginated(
        self,
        orcid: str,
        page_size: int = 100,
    ) -> tuple[list[dict[str, Any]], int]:
        return self._search_research_product_pages(
            product_type="dataset",
            author_orcid=orcid,
            page_size=page_size,
        )

    def search_datasets_by_names_paginated(
        self,
        names: Iterable[str],
        page_size: int = 100,
    ) -> tuple[list[dict[str, Any]], int]:
        clean_names = sorted({name.strip() for name in names if name and name.strip()})
        combined: dict[str, dict[str, Any]] = {}
        total_pages = 0

        for name in clean_names:
            records, pages_read = self._search_research_product_pages(
                product_type="dataset",
                author_full_name=name,
                page_size=page_size,
            )
            total_pages += pages_read
            for record in records:
                key = self._record_identity(record)
                if key:
                    combined[key] = record

        return list(combined.values()), total_pages

    def search_datasets_by_orcid(self, orcid: str, page_size: int = 100) -> list[dict[str, Any]]:
        records, _ = self.search_datasets_by_orcid_paginated(orcid, page_size=page_size)
        return records

    def search_datasets_by_names(self, names: Iterable[str], page_size: int = 100) -> list[dict[str, Any]]:
        records, _ = self.search_datasets_by_names_paginated(names, page_size=page_size)
        return records

    def get_author_profile(self, orcid: str) -> dict[str, Any]:
        payload = self._call_tool(
            "openaire_get_author_profile",
            {
                "orcid": orcid, "product_type": ["dataset"], "limit": 10,
                "include_coauthors": False, "response_format": "json",
            },
        )
        return self._extract_record(payload)

    def search_publications_by_title(self, title: str, page_size: int = 10) -> list[dict[str, Any]]:
        payload = self._call_tool(
            "openaire_search_research_products",
            {
                "type": ["publication"], "main_title": title, "page": 1,
                "page_size": page_size, "detail": "full", "response_format": "json",
            },
        )
        return self._extract_results(payload)

    def get_product_details(self, identifier: str) -> dict[str, Any]:
        payload = self._call_tool(
            "openaire_get_research_product_details",
            {"identifier": identifier, "response_format": "json"},
        )
        return self._extract_record(payload)

    @staticmethod
    def _graph_identifier(entity: dict[str, Any], scheme: str) -> str | None:
        """Extract an identifier from a Graph API V3 research-product stub."""
        wanted = scheme.casefold()
        identifiers = entity.get("identifiers") or []
        if isinstance(identifiers, dict):
            identifiers = [identifiers]
        for item in identifiers:
            if not isinstance(item, dict):
                continue
            item_scheme = str(item.get("idScheme") or item.get("scheme") or "").casefold()
            identifier = str(item.get("id") or item.get("value") or "").strip()
            if identifier and item_scheme == wanted:
                return identifier.removeprefix("50|") if wanted == "openaireidentifier" else identifier
        return None

    @classmethod
    def _normalise_graph_link(cls, link: dict[str, Any]) -> dict[str, Any]:
        """Convert a Graph API V3 link into the shape consumed by app.py."""
        source = link.get("source") if isinstance(link.get("source"), dict) else {}
        target = link.get("target") if isinstance(link.get("target"), dict) else {}
        source_doi = cls._graph_identifier(source, "doi")
        source_pid = cls._graph_identifier(source, "openaireIdentifier") or source_doi

        authors: list[dict[str, str | None]] = []
        for author in source.get("authors") or []:
            if not isinstance(author, dict):
                authors.append({"name": str(author), "orcid": None})
                continue
            authors.append({
                "name": str(author.get("name") or "Unknown author"),
                "orcid": cls._graph_identifier(author, "orcid"),
            })

        return {
            "sourcePid": source_pid,
            "sourceDoi": source_doi,
            "sourceTitle": source.get("title"),
            "sourceAuthors": authors,
            "sourcePublicationDate": source.get("publicationDate"),
            "source": source,
            "target": target,
            "relType": link.get("relType"),
            "provenance": link.get("provenance") or [],
        }

    def get_incoming_publication_links(self, pid: str, page_size: int = 100) -> list[dict[str, Any]]:
        """Return publication→dataset citation links from OpenAIRE Graph API V3.

        This endpoint exposes the citing publication together with title, DOI,
        publication date and authors, so a separate direct ScholeXplorer call is
        neither required nor used. Graph links pagination is zero-based.
        """
        try:
            import httpx
        except ImportError as exc:
            raise ProviderError(
                "The HTTP client is not installed. Run: pip install -r requirements.txt"
            ) from exc

        safe_page_size = max(1, min(int(page_size), 100))
        all_results: list[dict[str, Any]] = []
        page = 0
        total_pages = 1
        total_links = 0

        try:
            with httpx.Client(
                timeout=httpx.Timeout(self.timeout, connect=min(self.timeout, 30)),
                follow_redirects=True,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "Connected-Contributions/5.6",
                },
            ) as client:
                while page < total_pages:
                    response = client.get(
                        OPENAIRE_GRAPH_LINKS_URL,
                        params={
                            "targetPid": pid,
                            "relation": "Cites",
                            "sourceType": "publication",
                            "page": page,
                            "pageSize": safe_page_size,
                        },
                    )
                    response.raise_for_status()
                    payload = response.json()
                    if not isinstance(payload, dict):
                        raise ProviderError(
                            "OpenAIRE Graph API V3 returned an unexpected response structure."
                        )

                    header = payload.get("header") if isinstance(payload.get("header"), dict) else {}
                    page_results = payload.get("results") if isinstance(payload.get("results"), list) else []
                    all_results.extend(
                        self._normalise_graph_link(item)
                        for item in page_results
                        if isinstance(item, dict)
                    )
                    total_pages = max(1, int(header.get("totalPages") or 1))
                    total_links = max(total_links, int(header.get("totalLinks") or 0))
                    page += 1
        except ProviderError:
            raise
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise ProviderError(
                f"OpenAIRE Graph API V3 citation-link request failed for {pid}: {exc}"
            ) from exc

        if total_links > 0 and not all_results:
            raise ProviderError(
                f"OpenAIRE Graph API V3 reports {total_links} incoming citation link(s) for {pid}, "
                "but returned no identifiable link records."
            )
        return all_results


PROJECT_CODE_PATTERN = re.compile(
    r"\b(?:PID\d{4}-[A-Z0-9-]+|[A-Z]{2,}\d{2,}(?:-[A-Z0-9-]+)*)\b",
    flags=re.IGNORECASE,
)


def extract_project_codes(text: str | None) -> list[str]:
    if not text:
        return []
    return sorted({match.group(0) for match in PROJECT_CODE_PATTERN.finditer(text)})
