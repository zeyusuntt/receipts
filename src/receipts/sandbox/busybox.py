"""Load the pinned static busybox used inside Token Factory sandboxes."""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Callable
from pathlib import Path

import httpx


BUSYBOX_URL = (
    "https://busybox.net/downloads/binaries/1.35.0-x86_64-linux-musl/busybox"
)
BUSYBOX_SHA256 = "6e123e7f3202a8c1e9b1f94d8941580a25135382b99e8d3e34fb858bba311348"
BUSYBOX_SIZE = 1_131_168
BUSYBOX_FILENAME = "busybox-1.35.0-x86_64-musl"
_DOWNLOAD_TIMEOUT_S = 30.0


def _fetch(url: str) -> bytes:
    response = httpx.get(url, timeout=_DOWNLOAD_TIMEOUT_S)
    response.raise_for_status()
    return response.content


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_busybox(
    cache_dir: Path | None = None,
    *,
    fetch: Callable[[str], bytes] = _fetch,
) -> bytes:
    """Return the pinned busybox, reusing only a digest-valid cache entry."""

    directory = (
        Path.home() / ".cache" / "receipts"
        if cache_dir is None
        else Path(cache_dir)
    )
    cache_path = directory / BUSYBOX_FILENAME
    try:
        cached = cache_path.read_bytes()
    except FileNotFoundError:
        pass
    else:
        if _digest(cached) == BUSYBOX_SHA256:
            return cached

    downloaded = fetch(BUSYBOX_URL)
    if not isinstance(downloaded, bytes):
        raise TypeError("busybox fetch must return bytes")
    actual_digest = _digest(downloaded)
    if actual_digest != BUSYBOX_SHA256:
        raise ValueError(
            "busybox digest mismatch: "
            f"expected {BUSYBOX_SHA256}, got {actual_digest}",
        )

    directory.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=directory,
        prefix=f".{BUSYBOX_FILENAME}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(downloaded)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(cache_path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return downloaded
