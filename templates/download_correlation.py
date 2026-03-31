"""下载请求相关性子层。

本模块只服务单目标下载：
- 建模一次下载意图
- 识别哪个 Fetch response 真正对应目标下载
- 在命中时改写下载文件名
- 管理受限的 Fetch 生命周期
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlparse


@dataclass(frozen=True)
class DownloadIntent:
    target_name: str
    rename_requested: bool
    href: str | None
    download_attr: str | None


def _header_value(headers: list[dict[str, Any]], name: str) -> str | None:
    for item in headers:
        if str(item.get("name", "")).lower() == name.lower():
            value = item.get("value")
            return str(value) if value not in (None, "") else None
    return None


def _response_url(event: Mapping[str, Any]) -> str | None:
    request = event.get("request")
    if isinstance(request, Mapping):
        url = request.get("url")
        if url not in (None, ""):
            return str(url).strip() or None
    url = event.get("url")
    if url not in (None, ""):
        return str(url).strip() or None
    return None


def _normalize_url_key(value: str | None) -> tuple[str, str, str] | None:
    if not value:
        return None
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return None
    return parsed.scheme.lower(), parsed.netloc.lower(), parsed.path


def _rewrite_download_response_headers(headers: list[dict[str, Any]], target_name: str) -> list[dict[str, Any]]:
    rewritten: list[dict[str, Any]] = []
    seen = False
    for item in headers:
        header_name = str(item.get("name", ""))
        if header_name.lower() == "content-disposition":
            rewritten.append(
                {"name": header_name or "Content-Disposition", "value": f'attachment; filename="{target_name}"'}
            )
            seen = True
        else:
            rewritten.append(dict(item))
    if not seen:
        rewritten.append({"name": "Content-Disposition", "value": f'attachment; filename="{target_name}"'})
    return rewritten


def _looks_like_download_response(event: Mapping[str, Any]) -> bool:
    headers = event.get("responseHeaders")
    if not isinstance(headers, list):
        return False
    content_disposition = _header_value(headers, "Content-Disposition")
    if not content_disposition:
        return False
    lowered = content_disposition.lower()
    return "attachment" in lowered or "filename=" in lowered


@dataclass
class DownloadMatcher:
    intent: DownloadIntent

    def matches_response(self, event: Mapping[str, Any]) -> bool:
        if not _looks_like_download_response(event):
            return False
        if not self.intent.href:
            return True
        response_key = _normalize_url_key(_response_url(event))
        href_key = _normalize_url_key(self.intent.href)
        if response_key is None or href_key is None:
            return False
        return response_key == href_key


class ScopedDownloadInterceptor:
    def __init__(self, owner, intent: DownloadIntent, matcher: DownloadMatcher):
        self._owner = owner
        self._intent = intent
        self._matcher = matcher
        self._driver = getattr(owner, "_driver", None) or getattr(owner, "driver", None)
        self._runner = getattr(owner, "_run_cdp", None)
        self._matched = False
        self._enabled = False

    @property
    def matched(self) -> bool:
        return self._matched

    def _continue_response(self, event: Mapping[str, Any], headers: list[dict[str, Any]] | None = None) -> None:
        params: dict[str, Any] = {"requestId": event["requestId"]}
        status_code = event.get("responseStatusCode")
        if status_code is not None:
            params["responseCode"] = status_code
        response_headers = headers if headers is not None else list(event.get("responseHeaders") or [])
        if response_headers:
            params["responseHeaders"] = response_headers
        self._runner("Fetch.continueResponse", **params)

    def _on_fetch_request_paused(self, **event: Any) -> None:
        try:
            if self._matched or not self._matcher.matches_response(event):
                self._continue_response(event)
                return
            rewritten = _rewrite_download_response_headers(
                list(event.get("responseHeaders") or []),
                self._intent.target_name,
            )
            self._matched = True
            self._continue_response(event, headers=rewritten)
        except Exception:
            self._continue_response(event)

    def enable(self) -> None:
        if self._enabled:
            return
        self._runner("Fetch.enable", patterns=[{"requestStage": "Response"}])
        self._driver.set_callback("Fetch.requestPaused", self._on_fetch_request_paused)
        self._enabled = True

    def cleanup(self) -> None:
        if not self._enabled:
            return
        try:
            self._runner("Fetch.disable")
        finally:
            self._driver.set_callback("Fetch.requestPaused", None)
            self._enabled = False


def prepare_download_interceptor(owner, intent: DownloadIntent) -> ScopedDownloadInterceptor | None:
    if not intent.rename_requested:
        return None
    driver = getattr(owner, "_driver", None) or getattr(owner, "driver", None)
    runner = getattr(owner, "_run_cdp", None)
    if not callable(getattr(driver, "set_callback", None)) or not callable(runner):
        return None
    return ScopedDownloadInterceptor(owner, intent, DownloadMatcher(intent))
