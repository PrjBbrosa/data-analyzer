"""HTTPS download policy for the TraceLab extension manager.

This module is transport only: timeouts, redirects, retries, cancellation,
length caps, part-file caching, and SHA-256 verification. It must stay free of
Tk/Qt and of TUF metadata logic so it can run off the UI thread.
"""

from __future__ import annotations

import hashlib
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import Request

_CHUNK_SIZE = 64 * 1024
_PART_SUFFIX = ".part"
_PART_META_SUFFIX = ".part.meta"

# High-level callers place complete files under cache/; never site-packages.
_FORBIDDEN_DEST_PARTS = frozenset({"site-packages"})


class DownloadCancelled(Exception):
    """Raised when a cooperative cancel event is set mid-transfer."""


class DownloadPolicyError(Exception):
    """Transport or integrity failure. Never means a component is not_installed."""

    def __init__(self, message: str, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class DownloadPolicy:
    trusted_origins: tuple[str, ...]
    connect_timeout_s: float = 15.0
    read_timeout_s: float = 30.0
    max_retries: int = 3
    retry_backoff_s: float = 0.5
    max_redirects: int = 5
    max_length: int = 512 * 1024 * 1024
    require_https: bool = True
    verify_tls: bool = True


def assert_https_trusted_url(
    url: str,
    trusted_origins: Sequence[str],
    *,
    require_https: bool = True,
) -> urllib.parse.ParseResult:
    """Reject non-HTTPS, credentialed, or off-allowlist URLs before any I/O."""

    parsed = urllib.parse.urlparse(url)
    if require_https and parsed.scheme.lower() != "https":
        raise DownloadPolicyError(
            f"refusing non-HTTPS URL scheme {parsed.scheme!r}",
            "VERIFICATION_FAILED",
        )
    if parsed.scheme.lower() not in {"https", "http"}:
        raise DownloadPolicyError(
            f"unsupported URL scheme {parsed.scheme!r}",
            "VERIFICATION_FAILED",
        )
    if parsed.username is not None or parsed.password is not None:
        raise DownloadPolicyError(
            "refusing URLs that embed credentials",
            "VERIFICATION_FAILED",
        )
    host = (parsed.hostname or "").lower()
    if not host:
        raise DownloadPolicyError("URL is missing a host", "VERIFICATION_FAILED")
    allowed = {item.lower() for item in trusted_origins}
    if host not in allowed:
        raise DownloadPolicyError(
            f"host {host!r} is not a trusted origin",
            "VERIFICATION_FAILED",
        )
    return parsed


def resolve_redirect_url(
    current_url: str,
    location: str,
    policy: DownloadPolicy,
    hop: int,
) -> str:
    """Apply HTTPS + trusted-origin policy to one redirect hop."""

    if hop > policy.max_redirects:
        raise DownloadPolicyError(
            f"too many redirects (>{policy.max_redirects})",
            "NETWORK_CHECK_FAILED",
        )
    if not location:
        raise DownloadPolicyError("redirect is missing Location", "VERIFICATION_FAILED")
    next_url = urllib.parse.urljoin(current_url, location)
    assert_https_trusted_url(
        next_url,
        policy.trusted_origins,
        require_https=policy.require_https,
    )
    return next_url


def _ssl_context(policy: DownloadPolicy) -> ssl.SSLContext | None:
    if not policy.require_https:
        return None
    if policy.verify_tls:
        return ssl.create_default_context()
    context = ssl._create_unverified_context()  # noqa: SLF001 — tests only
    return context


def _timeout(policy: DownloadPolicy) -> float:
    return min(policy.connect_timeout_s, policy.read_timeout_s)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _assert_cache_dest(dest_path: Path) -> None:
    parts = {part.lower() for part in dest_path.parts}
    if parts & _FORBIDDEN_DEST_PARTS:
        raise DownloadPolicyError(
            "download destination must not be a module search path",
            "VERIFICATION_FAILED",
        )


def _part_paths(dest_path: Path) -> tuple[Path, Path]:
    part = dest_path.with_name(dest_path.name + _PART_SUFFIX)
    meta = dest_path.with_name(dest_path.name + _PART_META_SUFFIX)
    return part, meta


def _load_part_meta(meta_path: Path) -> dict[str, Any]:
    if not meta_path.is_file():
        return {}
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_part_meta(meta_path: Path, payload: Mapping[str, Any]) -> None:
    meta_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, DownloadCancelled):
        return False
    if isinstance(exc, DownloadPolicyError):
        return exc.reason_code == "NETWORK_CHECK_FAILED"
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code >= 500
    return isinstance(
        exc,
        (urllib.error.URLError, TimeoutError, ConnectionError, OSError),
    )


class _TrustedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, policy: DownloadPolicy) -> None:
        super().__init__()
        self._policy = policy
        self._hops = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        self._hops += 1
        location = headers.get("Location") or newurl
        resolve_redirect_url(req.full_url, str(location), self._policy, self._hops)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def build_policy_opener(policy: DownloadPolicy) -> urllib.request.OpenerDirector:
    handlers: list[urllib.request.BaseHandler] = [_TrustedRedirectHandler(policy)]
    context = _ssl_context(policy)
    if context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=context))
    return urllib.request.build_opener(*handlers)


def download_verified_file(
    url: str,
    dest_path: Path,
    *,
    expected_sha256: str,
    expected_length: int,
    policy: DownloadPolicy,
    cancel_event: Any | None = None,
    urlopen: Callable[..., Any] | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> Path:
    """Download ``url`` to ``dest_path`` with resume, cap, and SHA-256 check.

    Incomplete bytes stay in a sibling ``.part`` file. The final path is written
    only after length and digest match, so a half-written object never becomes a
    module search entry.
    """

    _assert_cache_dest(dest_path)
    expected = expected_sha256.lower()
    if expected_length < 0:
        raise DownloadPolicyError("expected_length must be >= 0", "VERIFICATION_FAILED")
    if expected_length > policy.max_length:
        raise DownloadPolicyError(
            "declared length exceeds the download cap",
            "VERIFICATION_FAILED",
        )
    assert_https_trusted_url(
        url,
        policy.trusted_origins,
        require_https=policy.require_https,
    )
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    part_path, meta_path = _part_paths(dest_path)
    if dest_path.is_file():
        if dest_path.stat().st_size == expected_length and _sha256_file(dest_path) == expected:
            return dest_path
        dest_path.unlink()

    sleep = sleeper or time.sleep
    last_error: BaseException | None = None
    attempts = policy.max_retries + 1
    for attempt in range(attempts):
        if cancel_event is not None and cancel_event.is_set():
            raise DownloadCancelled("download cancelled")
        try:
            _download_attempt(
                url,
                dest_path=dest_path,
                part_path=part_path,
                meta_path=meta_path,
                expected_sha256=expected,
                expected_length=expected_length,
                policy=policy,
                cancel_event=cancel_event,
                urlopen=urlopen,
            )
            return dest_path
        except DownloadCancelled:
            raise
        except DownloadPolicyError as exc:
            last_error = exc
            if not _retryable(exc) or attempt + 1 >= attempts:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            last_error = exc
            if not _retryable(exc) or attempt + 1 >= attempts:
                raise DownloadPolicyError(str(exc), "NETWORK_CHECK_FAILED") from exc
        sleep(policy.retry_backoff_s * (2**attempt))
    raise DownloadPolicyError(str(last_error), "NETWORK_CHECK_FAILED")


def _download_attempt(
    url: str,
    *,
    dest_path: Path,
    part_path: Path,
    meta_path: Path,
    expected_sha256: str,
    expected_length: int,
    policy: DownloadPolicy,
    cancel_event: Any | None,
    urlopen: Callable[..., Any] | None,
) -> None:
    resume_from = 0
    meta = _load_part_meta(meta_path)
    identity_ok = (
        meta.get("expected_sha256") == expected_sha256
        and int(meta.get("expected_length") or -1) == expected_length
        and meta.get("url") == url
    )
    if part_path.is_file() and identity_ok:
        resume_from = part_path.stat().st_size
        if resume_from > expected_length:
            part_path.unlink()
            resume_from = 0
        elif resume_from == expected_length:
            _finalize_part(part_path, dest_path, meta_path, expected_sha256, expected_length)
            return
    elif part_path.exists():
        part_path.unlink()
        if meta_path.exists():
            meta_path.unlink()
        resume_from = 0

    headers = {"Accept": "*/*"}
    saved_etag = str(meta.get("etag") or "") if identity_ok else ""
    if resume_from:
        headers["Range"] = f"bytes={resume_from}-"
        if saved_etag:
            headers["If-Range"] = saved_etag
    request = Request(url, headers=headers, method="GET")
    opener = None if urlopen is not None else build_policy_opener(policy)
    context = _ssl_context(policy)
    timeout = _timeout(policy)

    def _open() -> Any:
        if urlopen is not None:
            try:
                return urlopen(request, timeout=timeout, context=context)
            except TypeError:
                return urlopen(request, timeout=timeout)
        return opener.open(request, timeout=timeout)  # type: ignore[union-attr]

    try:
        response = _open()
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and resume_from:
            part_path.unlink(missing_ok=True)
            raise DownloadPolicyError(
                "server rejected resume range",
                "NETWORK_CHECK_FAILED",
            ) from exc
        if exc.code >= 500:
            raise DownloadPolicyError(str(exc), "NETWORK_CHECK_FAILED") from exc
        raise DownloadPolicyError(str(exc), "VERIFICATION_FAILED") from exc
    except urllib.error.URLError as exc:
        raise DownloadPolicyError(str(exc.reason or exc), "NETWORK_CHECK_FAILED") from exc

    try:
        status = getattr(response, "status", None) or response.getcode()
        if resume_from and status == 200:
            part_path.unlink(missing_ok=True)
            resume_from = 0
        elif resume_from and status != 206:
            raise DownloadPolicyError(
                f"resume expected HTTP 206, got {status}",
                "NETWORK_CHECK_FAILED",
            )
        elif not resume_from and status not in {200, 206}:
            raise DownloadPolicyError(f"unexpected HTTP status {status}", "NETWORK_CHECK_FAILED")

        headers_obj = response.info() if hasattr(response, "info") else getattr(response, "headers", None)
        content_length = _header_int(headers_obj, "Content-Length")
        if content_length is not None:
            total = resume_from + content_length if status == 206 else content_length
            if total > policy.max_length:
                raise DownloadPolicyError("server length exceeds download cap", "VERIFICATION_FAILED")
            if total != expected_length:
                raise DownloadPolicyError(
                    "Content-Length does not match trusted expected_length",
                    "VERIFICATION_FAILED",
                )

        etag = _header_str(headers_obj, "ETag")
        if resume_from and status == 206:
            range_start, range_end, range_total = _parse_content_range(
                _header_str(headers_obj, "Content-Range")
            )
            if range_start != resume_from:
                part_path.unlink(missing_ok=True)
                meta_path.unlink(missing_ok=True)
                raise DownloadPolicyError(
                    "Content-Range start does not match the requested resume offset",
                    "NETWORK_CHECK_FAILED",
                )
            if range_total is not None and range_total != expected_length:
                part_path.unlink(missing_ok=True)
                meta_path.unlink(missing_ok=True)
                raise DownloadPolicyError(
                    "Content-Range total does not match trusted expected_length",
                    "VERIFICATION_FAILED",
                )
            if range_end + 1 > expected_length:
                part_path.unlink(missing_ok=True)
                meta_path.unlink(missing_ok=True)
                raise DownloadPolicyError(
                    "Content-Range end exceeds trusted expected_length",
                    "VERIFICATION_FAILED",
                )
            if saved_etag and etag and _normalize_etag(saved_etag) != _normalize_etag(etag):
                part_path.unlink(missing_ok=True)
                meta_path.unlink(missing_ok=True)
                raise DownloadPolicyError(
                    "ETag changed for a resumed download",
                    "NETWORK_CHECK_FAILED",
                )
        _write_part_meta(
            meta_path,
            {
                "expected_sha256": expected_sha256,
                "expected_length": expected_length,
                "url": url,
                "etag": etag,
            },
        )
        mode = "ab" if resume_from and status == 206 else "wb"
        received = resume_from
        with part_path.open(mode) as handle:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise DownloadCancelled("download cancelled")
                chunk = response.read(_CHUNK_SIZE)
                if not chunk:
                    break
                received += len(chunk)
                if received > policy.max_length:
                    raise DownloadPolicyError("download exceeded length cap", "VERIFICATION_FAILED")
                if received > expected_length:
                    raise DownloadPolicyError(
                        "downloaded bytes exceed trusted expected_length",
                        "VERIFICATION_FAILED",
                    )
                handle.write(chunk)
        if received != expected_length:
            raise DownloadPolicyError(
                f"incomplete download ({received} != {expected_length})",
                "NETWORK_CHECK_FAILED",
            )
        _finalize_part(part_path, dest_path, meta_path, expected_sha256, expected_length)
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()


def _finalize_part(
    part_path: Path,
    dest_path: Path,
    meta_path: Path,
    expected_sha256: str,
    expected_length: int,
) -> None:
    if not part_path.is_file() or part_path.stat().st_size != expected_length:
        raise DownloadPolicyError("part file is incomplete", "NETWORK_CHECK_FAILED")
    digest = _sha256_file(part_path)
    if digest != expected_sha256:
        part_path.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)
        raise DownloadPolicyError(
            "SHA-256 mismatch after download",
            "VERIFICATION_FAILED",
        )
    dest_path.unlink(missing_ok=True)
    part_path.replace(dest_path)
    meta_path.unlink(missing_ok=True)


def _header_int(headers: Any, name: str) -> int | None:
    if headers is None:
        return None
    raw = headers.get(name) if hasattr(headers, "get") else None
    if raw in (None, ""):
        return None
    try:
        return int(str(raw).strip())
    except ValueError as exc:
        raise DownloadPolicyError(f"invalid {name} header", "VERIFICATION_FAILED") from exc


def _header_str(headers: Any, name: str) -> str | None:
    if headers is None or not hasattr(headers, "get"):
        return None
    raw = headers.get(name)
    return str(raw) if raw else None


def _normalize_etag(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if text[:2].lower() == "w/":
        text = text[2:].strip()
    if len(text) >= 2 and text[0] == text[-1] == '"':
        text = text[1:-1]
    return text or None


def _parse_content_range(header: str | None) -> tuple[int, int, int | None]:
    if not header:
        raise DownloadPolicyError(
            "206 response is missing Content-Range",
            "VERIFICATION_FAILED",
        )
    text = header.strip()
    if not text.lower().startswith("bytes "):
        raise DownloadPolicyError("unsupported Content-Range unit", "VERIFICATION_FAILED")
    spec = text.split(None, 1)[1]
    range_part, separator, total_part = spec.partition("/")
    if not separator or "-" not in range_part:
        raise DownloadPolicyError("invalid Content-Range", "VERIFICATION_FAILED")
    start_s, end_s = range_part.split("-", 1)
    try:
        start = int(start_s)
        end = int(end_s)
    except ValueError as exc:
        raise DownloadPolicyError("invalid Content-Range", "VERIFICATION_FAILED") from exc
    if start < 0 or end < start:
        raise DownloadPolicyError("invalid Content-Range", "VERIFICATION_FAILED")
    if total_part == "*":
        return start, end, None
    try:
        total = int(total_part)
    except ValueError as exc:
        raise DownloadPolicyError("invalid Content-Range", "VERIFICATION_FAILED") from exc
    return start, end, total
