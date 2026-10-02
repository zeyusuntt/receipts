from __future__ import annotations

import hashlib
from pathlib import Path

import pytest


def _module():
    from receipts.sandbox import busybox

    return busybox


def test_valid_cached_busybox_is_reused_without_downloading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    module = _module()
    payload = b"cached trusted busybox"
    monkeypatch.setattr(module, "BUSYBOX_SHA256", hashlib.sha256(payload).hexdigest())
    cache_path = tmp_path / module.BUSYBOX_FILENAME
    cache_path.write_bytes(payload)

    def fail_fetch(_url: str) -> bytes:
        raise AssertionError("a valid cache entry must not be downloaded again")

    assert module.load_busybox(tmp_path, fetch=fail_fetch) == payload


def test_missing_busybox_is_downloaded_verified_and_atomically_cached(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    module = _module()
    payload = b"downloaded trusted busybox"
    monkeypatch.setattr(module, "BUSYBOX_SHA256", hashlib.sha256(payload).hexdigest())
    fetched: list[str] = []

    def fetch(url: str) -> bytes:
        fetched.append(url)
        return payload

    assert module.load_busybox(tmp_path, fetch=fetch) == payload
    assert fetched == [module.BUSYBOX_URL]
    assert (tmp_path / module.BUSYBOX_FILENAME).read_bytes() == payload
    assert not list(tmp_path.glob("*.tmp"))


def test_wrong_busybox_digest_raises_and_leaves_no_cache_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    module = _module()
    monkeypatch.setattr(
        module,
        "BUSYBOX_SHA256",
        hashlib.sha256(b"expected busybox").hexdigest(),
    )

    with pytest.raises(ValueError, match="digest"):
        module.load_busybox(tmp_path, fetch=lambda _url: b"wrong busybox")

    assert not (tmp_path / module.BUSYBOX_FILENAME).exists()
    assert list(tmp_path.iterdir()) == []
