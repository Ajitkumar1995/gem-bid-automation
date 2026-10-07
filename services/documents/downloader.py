"""Safe, bounded retrieval for external documents linked by tender PDFs."""
from dataclasses import dataclass
from email.message import Message
import ipaddress
import os
import re
import shutil
import socket
from urllib.parse import unquote, urljoin, urlparse

import requests
from django.utils.text import get_valid_filename
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
MAX_TOTAL_DOWNLOAD_BYTES = 250 * 1024 * 1024
MAX_REDIRECTS = 5
REQUEST_TIMEOUT = (8, 30)
ALLOWED_TYPES = {
    "application/pdf", "application/octet-stream", "application/zip",
    "application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel.sheet.macroenabled.12", "text/csv",
    "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-powerpoint", "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


class DownloadError(Exception):
    """A linked URL could not be fetched as a safe document."""


class BrowserFallbackRequired(DownloadError):
    """The target returned a web page rather than a directly retrievable file."""


@dataclass
class DownloadedFile:
    content: bytes
    filename: str
    content_type: str
    final_url: str


def _validate_public_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise DownloadError("Only absolute HTTP or HTTPS document links can be downloaded.")
    if parsed.username or parsed.password:
        raise DownloadError("Links containing embedded credentials are not allowed.")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)}
    except (OSError, ValueError) as exc:
        raise DownloadError("The document host could not be resolved.") from exc
    if not addresses:
        raise DownloadError("The document host has no public address.")
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
        if not ip.is_global:
            raise DownloadError("Private or reserved network addresses are not allowed.")
    return parsed


def _safe_filename(response, final_url):
    message = Message()
    message["content-disposition"] = response.headers.get("content-disposition", "")
    supplied = message.get_filename() or unquote(urlparse(final_url).path.rsplit("/", 1)[-1])
    return _sanitize_filename(supplied) or "linked-document"


def _sanitize_filename(supplied):
    supplied = supplied.replace("\\", "/").rsplit("/", 1)[-1]
    try:
        return get_valid_filename(supplied)[:240]
    except Exception:
        return ""


def _make_session():
    session = requests.Session()
    session.trust_env = False
    retry = Retry(
        total=3,
        connect=3,
        read=2,
        status=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        respect_retry_after_header=True,
    )
    session.mount("http://", HTTPAdapter(max_retries=retry))
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": "GemBidDocumentFetcher/1.0 (+document retrieval)"})
    return session


def _read_response(response, final_url):
    content_type = response.headers.get("content-type", "application/octet-stream").split(";", 1)[0].strip().lower()
    if content_type in {"text/html", "application/xhtml+xml"}:
        raise BrowserFallbackRequired("The link returned a web page; trying browser retrieval.")
    if content_type not in ALLOWED_TYPES:
        raise DownloadError(f"Unsupported linked file type: {content_type or 'unknown'}.")
    length = response.headers.get("content-length")
    if length and int(length) > MAX_DOWNLOAD_BYTES:
        raise DownloadError("The linked file exceeds the 50 MB download limit.")
    chunks = []
    total = 0
    for chunk in response.iter_content(128 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_DOWNLOAD_BYTES:
            raise DownloadError("The linked file exceeds the 50 MB download limit.")
        chunks.append(chunk)
    if not total:
        raise DownloadError("The linked URL returned an empty file.")
    return DownloadedFile(b"".join(chunks), _safe_filename(response, final_url), content_type, final_url)


def download_http(url):
    session = _make_session()
    current_url = url
    try:
        for redirect_count in range(MAX_REDIRECTS + 1):
            _validate_public_url(current_url)
            response = session.get(current_url, stream=True, timeout=REQUEST_TIMEOUT, allow_redirects=False)
            if response.is_redirect or response.is_permanent_redirect:
                location = response.headers.get("location")
                response.close()
                if not location or redirect_count >= MAX_REDIRECTS:
                    raise DownloadError("The linked URL redirected too many times.")
                current_url = urljoin(current_url, location)
                continue
            response.raise_for_status()
            return _read_response(response, current_url)
        raise DownloadError("The linked URL redirected too many times.")
    except BrowserFallbackRequired:
        raise
    except DownloadError:
        raise
    except requests.RequestException as exc:
        raise BrowserFallbackRequired(f"Direct HTTP retrieval failed: {exc.__class__.__name__}.") from exc
    finally:
        session.close()


def download_with_browser(url):
    """Use Playwright for link pages that require browser navigation or a click."""
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise DownloadError("Playwright is not installed for browser fallback.") from exc

    _validate_public_url(url)
    result = {}
    with sync_playwright() as playwright:
        chrome_path = os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH") or shutil.which("chromium") or shutil.which("google-chrome")
        try:
            browser = playwright.chromium.launch(headless=True, executable_path=chrome_path)
        except Exception as exc:
            raise DownloadError("Playwright Chromium is unavailable; install it with `playwright install chromium`.") from exc
        context = browser.new_context(accept_downloads=True)

        def guard_route(route):
            request_url = route.request.url
            if request_url.startswith(("data:", "blob:", "about:")):
                route.continue_()
                return
            try:
                _validate_public_url(request_url)
            except DownloadError:
                route.abort()
            else:
                route.continue_()

        context.route("**/*", guard_route)
        page = context.new_page()
        try:
            response = None
            try:
                with page.expect_download(timeout=8_000) as download_info:
                    response = page.goto(url, wait_until="domcontentloaded", timeout=25_000)
                download = download_info.value
                path = download.path()
                with open(path, "rb") as downloaded:
                    content = downloaded.read(MAX_DOWNLOAD_BYTES + 1)
                if len(content) > MAX_DOWNLOAD_BYTES:
                    raise DownloadError("The linked file exceeds the 50 MB download limit.")
                result["file"] = DownloadedFile(content, _sanitize_filename(download.suggested_filename) or "linked-document", "application/octet-stream", page.url)
            except PlaywrightTimeoutError:
                pass
            if "file" not in result and response is not None:
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if content_type in ALLOWED_TYPES:
                    content_length = int(response.headers.get("content-length", "0") or 0)
                    if content_length > MAX_DOWNLOAD_BYTES:
                        raise DownloadError("The linked file exceeds the 50 MB download limit.")
                    content = response.body()
                    if len(content) > MAX_DOWNLOAD_BYTES:
                        raise DownloadError("The linked file exceeds the 50 MB download limit.")
                    result["file"] = DownloadedFile(content, _safe_filename(response, page.url), content_type, page.url)

            if "file" not in result:
                anchors = page.locator("a[href]")
                count = min(anchors.count(), 20)
                for index in range(count):
                    anchor = anchors.nth(index)
                    href = urljoin(page.url, anchor.get_attribute("href") or "")
                    text = (anchor.inner_text(timeout=1_000) or "").strip().lower()
                    if not (re.search(r"\.(pdf|xlsx?|csv|docx?|zip)(?:$|[?#])", href, re.I) or any(word in text for word in ("download", "view file", "attachment"))):
                        continue
                    try:
                        _validate_public_url(href)
                        with page.expect_download(timeout=6_000) as download_info:
                            anchor.click(timeout=5_000)
                        download = download_info.value
                        path = download.path()
                        with open(path, "rb") as downloaded:
                            content = downloaded.read(MAX_DOWNLOAD_BYTES + 1)
                        if len(content) > MAX_DOWNLOAD_BYTES:
                            raise DownloadError("The linked file exceeds the 50 MB download limit.")
                        result["file"] = DownloadedFile(content, _sanitize_filename(download.suggested_filename) or "linked-document", "application/octet-stream", page.url)
                        break
                    except PlaywrightTimeoutError:
                        continue
            if "file" not in result:
                raise DownloadError("Browser fallback did not find a downloadable file.")
            return result["file"]
        finally:
            context.close()
            browser.close()


def download_document(url):
    try:
        return download_http(url)
    except BrowserFallbackRequired:
        return download_with_browser(url)
