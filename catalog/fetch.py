"""Polite, validated and locale-aware HTTP for public catalog endpoints."""
import hashlib
import json
import os
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

USER_AGENT = "SearchEvalResearch/0.1 (+search-relevance benchmarking; polite, cached)"
CHALLENGE_MARKERS = (
    b"verifying your connection", b"cf-injected", b"attention required", b"captcha"
)


@dataclass(frozen=True)
class RequestProfile:
    locale: str
    accept_language: str

    def cache_token(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


class Challenged(Exception):
    """The host served a bot challenge instead of content. Back off; never cache."""


class FetchError(Exception):
    """The transport failed, returned an HTTP error, or returned nothing."""


def curl_transport(url: str, profile: RequestProfile) -> bytes:
    result = subprocess.run(
        ["curl", "-sSLg", "--fail-with-body", "-m", "25", "-A", USER_AGENT,
         "-H", f"Accept-Language: {profile.accept_language}", url],
        capture_output=True,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise FetchError(f"curl exit {result.returncode} for {url}: {detail}")
    return result.stdout


class PoliteFetcher:
    """Cache only validated bodies and pace every live request by `delay`."""

    def __init__(self, cache_dir: Path, profile: RequestProfile, delay: float = 3.0,
                 transport: Callable[[str, RequestProfile], bytes] | None = None,
                 clock=time):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.profile = profile
        self.delay = delay
        self._transport = transport or curl_transport
        self._clock = clock
        self._last = float("-inf")

    def _key(self, url: str, namespace: str) -> Path:
        material = f"{namespace}\x00{self.profile.cache_token()}\x00{url}"
        digest = hashlib.sha256(material.encode()).hexdigest()
        return self.cache_dir / f"{digest}.bin"

    def get(self, url: str, namespace: str = "",
            validator: Callable[[bytes], None] | None = None) -> bytes:
        key = self._key(url, namespace)
        if key.exists():
            return key.read_bytes()

        wait = self.delay - (self._clock.monotonic() - self._last)
        if wait > 0:
            self._clock.sleep(wait)
        self._last = self._clock.monotonic()

        body = self._transport(url, self.profile)
        lowered = body.lower()
        if any(marker in lowered for marker in CHALLENGE_MARKERS):
            raise Challenged(url)
        if not body:
            raise FetchError(url)
        if validator is not None:
            validator(body)

        tmp = key.with_suffix(f".{os.getpid()}.tmp")
        try:
            tmp.write_bytes(body)
            os.replace(tmp, key)
        finally:
            tmp.unlink(missing_ok=True)
        return body
