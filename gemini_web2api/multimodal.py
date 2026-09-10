"""Multimodal: Scotty resumable upload for Gemini image input."""
import urllib.request
import time
import re
from urllib.parse import urlparse

from .config import CONFIG
from .gemini import load_cookie, make_sapisidhash, _get_ssl_ctx, log

UPLOAD_HOSTS = (
    "https://push.clients6.google.com/upload/",
    "https://content-push.googleapis.com/upload/",
)


def _get_page_tokens() -> dict:
    """Fetch WIZ_global_data tokens from Gemini page (Push-ID, X-Client-Pctx)."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Origin": "https://gemini.google.com",
        "Referer": "https://gemini.google.com/app",
    }
    cookie_str, sapisid = load_cookie()
    if cookie_str:
        headers["Cookie"] = cookie_str
    if sapisid:
        headers["Authorization"] = make_sapisidhash(sapisid)
    try:
        req = urllib.request.Request("https://gemini.google.com/app", headers=headers)
        proxy = CONFIG.get("proxy")
        if proxy:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": proxy, "https": proxy}),
                urllib.request.HTTPSHandler(context=_get_ssl_ctx()),
            )
            resp = opener.open(req, timeout=30)
        else:
            resp = urllib.request.urlopen(req, context=_get_ssl_ctx(), timeout=30)
        html = resp.read().decode("utf-8", errors="replace")
        tokens = {}
        for key, pattern in [
            ("push_id", r'"qKIAYe":"([^"]+)"'),
            ("pctx", r'"Ylro7b":"([^"]+)"'),
            ("at", r'"SNlM0e":"([^"]+)"'),
        ]:
            m = re.search(pattern, html)
            if m:
                tokens[key] = m.group(1)
        return tokens
    except Exception as e:
        log(f"Page token fetch failed: {e}")
        return {}


_page_tokens_cache = {"tokens": {}, "ts": 0}


def _cached_page_tokens() -> dict:
    now = time.time()
    if now - _page_tokens_cache["ts"] > 600:
        _page_tokens_cache["tokens"] = _get_page_tokens()
        _page_tokens_cache["ts"] = now
    return _page_tokens_cache["tokens"]


def attachment_kind(mime: str) -> int:
    """Gemini Web attachment kind: 1 image, 2 video, 3 audio, 0 other (PDF/code)."""
    mime = (mime or "").lower()
    if mime.startswith("image/"):
        return 1
    if mime.startswith("video/"):
        return 2
    if mime.startswith("audio/"):
        return 3
    return 0


def filename_for_mime(mime: str, filename: str = "") -> str:
    name = (filename or "").replace("\r", "").replace("\n", "").strip()
    if name:
        return name
    mime = (mime or "").lower()
    if mime.startswith("image/"):
        ext = mime.split("/", 1)[-1].split("+", 1)[0] or "png"
        if ext == "jpeg":
            ext = "jpg"
        return f"image.{ext}"
    if mime.startswith("video/"):
        return "video.mp4"
    if mime.startswith("audio/"):
        return "audio.mp3"
    if mime == "application/pdf":
        return "document.pdf"
    if mime.startswith("text/") or "javascript" in mime or mime.endswith("json"):
        return "code.txt"
    return "file.bin"


def detect_file_mime(data: bytes, filename: str = "", fallback: str = "application/octet-stream") -> str:
    """Infer MIME from magic bytes, then filename."""
    if isinstance(data, bytes):
        if data.startswith(b"%PDF"):
            return "application/pdf"
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if data.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if data.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif"
        if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            return "image/webp"
        if data.startswith(b"ID3") or (len(data) > 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
            if filename.lower().endswith(".mp3"):
                return "audio/mpeg"
        if len(data) >= 12 and data[4:8] == b"ftyp":
            brand = data[8:12]
            if brand in (b"avif", b"avis"):
                return "image/avif"
            if brand in (b"heic", b"heix"):
                return "image/heic"
            return "video/mp4"
    name = (filename or "").lower()
    ext = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp", ".pdf": "application/pdf",
        ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
        ".mp3": "audio/mpeg", ".wav": "audio/wav", ".txt": "text/plain",
        ".md": "text/markdown", ".py": "text/x-python", ".js": "text/javascript",
        ".ts": "text/typescript", ".json": "application/json", ".css": "text/css",
        ".html": "text/html", ".csv": "text/csv", ".c": "text/x-c",
        ".cpp": "text/x-c++", ".rs": "text/x-rust", ".go": "text/x-go",
    }
    for suffix, mime in ext.items():
        if name.endswith(suffix):
            return mime
    if isinstance(data, bytes):
        image = detect_image_mime(data, "")
        if image:
            return image
    return fallback or "application/octet-stream"


def detect_image_mime(image_bytes: bytes, fallback: str = "image/png") -> str:
    """Infer a common raster image MIME type from its file signature."""
    if not isinstance(image_bytes, bytes):
        return fallback
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    if image_bytes.startswith(b"BM"):
        return "image/bmp"
    if image_bytes.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    if len(image_bytes) >= 12 and image_bytes[4:8] == b"ftyp":
        brand = image_bytes[8:12]
        if brand in (b"avif", b"avis"):
            return "image/avif"
        if brand in (b"heic", b"heix", b"hevc", b"hevx"):
            return "image/heic"
    return fallback


def _sanitize_upload_name(filename: str) -> str:
    name = (filename or "").replace("\r", "").replace("\n", "").strip()
    return name or "image.png"


def _upload_opener(ctx, proxy):
    if proxy:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}),
            urllib.request.HTTPSHandler(context=ctx),
        )
    return None


def _post(url, data, headers, ctx, opener, timeout):
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    if opener:
        return opener.open(req, timeout=timeout)
    return urllib.request.urlopen(req, context=ctx, timeout=timeout)


def upload_image(image_bytes: bytes, filename: str = "image.png", mime_type: str = "image/png") -> str:
    """Upload image via Scotty resumable upload. Returns file reference path."""
    cookie_str, sapisid = load_cookie()
    if not cookie_str:
        raise RuntimeError(
            "File input needs a gemini.google.com cookie. Sign in with Google so Cookie Sync "
            "can auto-collect SID/SAPISID, or set GEMINI_COOKIE."
        )

    tokens = _cached_page_tokens()
    push_id = tokens.get("push_id") or ""
    pctx = tokens.get("pctx") or ""
    if not push_id:
        raise RuntimeError(
            "Could not read Gemini upload tokens from gemini.google.com/app. "
            "Refresh GEMINI_COOKIE from a signed-in gemini.google.com session."
        )

    filename = _sanitize_upload_name(filename)
    ctx = _get_ssl_ctx()
    proxy = CONFIG.get("proxy")
    opener = _upload_opener(ctx, proxy)

    base_headers = {
        "Origin": "https://gemini.google.com",
        "Referer": "https://gemini.google.com/",
        "X-Tenant-Id": "bard-storage",
        "Push-ID": push_id,
        "Accept": "*/*",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Cookie": cookie_str,
    }
    if pctx:
        base_headers["X-Client-Pctx"] = pctx
    if sapisid:
        base_headers["Authorization"] = make_sapisidhash(sapisid)

    start_headers = dict(base_headers)
    start_headers.update({
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "X-Goog-Upload-Protocol": "resumable",
        "X-Goog-Upload-Command": "start",
        "X-Goog-Upload-Header-Content-Length": str(len(image_bytes)),
    })
    start_body = f"File name: {filename}".encode()

    last_err = None
    upload_url = None
    for host in UPLOAD_HOSTS:
        try:
            resp = _post(host, start_body, start_headers, ctx, opener, 30)
            upload_url = resp.headers.get("X-Goog-Upload-URL") or resp.headers.get("x-goog-upload-url")
            if upload_url:
                break
            last_err = RuntimeError(f"No upload URL in response headers from {host}")
        except Exception as e:
            last_err = e
            log(f"Upload start via {host} failed: {e}")
    if not upload_url:
        raise RuntimeError(f"Image upload start failed: {last_err}")

    log(f"Upload session started: {upload_url[:80]}...")

    upload_headers = dict(base_headers)
    upload_headers.update({
        "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
        "X-Goog-Upload-Command": "upload, finalize",
        "X-Goog-Upload-Offset": "0",
    })
    resp2 = _post(upload_url, image_bytes, upload_headers, ctx, opener, 60)
    file_ref = resp2.read().decode("utf-8", errors="replace").strip()
    if not file_ref or not file_ref.startswith("/"):
        raise RuntimeError(f"Invalid file reference: {file_ref[:100]}")

    log(f"Image uploaded: {filename} ({mime_type}) -> {file_ref[:50]}...")
    return file_ref


def fetch_image_bytes(url: str) -> bytes:
    """Fetch image from URL."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        log(f"Image fetch skipped for unsupported URL scheme: {parsed.scheme or 'none'}")
        return b""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        proxy = CONFIG.get("proxy")
        if proxy:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": proxy, "https": proxy}),
                urllib.request.HTTPSHandler(context=_get_ssl_ctx()),
            )
            resp = opener.open(req, timeout=30)
        else:
            resp = urllib.request.urlopen(req, context=_get_ssl_ctx(), timeout=30)
        return resp.read()
    except Exception as e:
        log(f"Image fetch failed: {e}")
        return b""
