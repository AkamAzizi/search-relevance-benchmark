import json

import pytest

from catalog.fetch import Challenged, FetchError, PoliteFetcher, RequestProfile


SV = RequestProfile("sv-SE", "sv-SE,sv;q=0.9,en;q=0.5")
EN = RequestProfile("en", "en-GB,en;q=0.9")


class FakeClock:
    def __init__(self): self.t, self.slept = 0.0, []
    def monotonic(self): return self.t
    def sleep(self, s): self.slept.append(s); self.t += s


def test_caches_validated_response_and_does_not_refetch(tmp_path):
    calls = []
    def transport(url, profile):
        calls.append((url, profile))
        return b'{"products": []}'
    f = PoliteFetcher(tmp_path, SV, delay=0.0, transport=transport, clock=FakeClock())
    validate = lambda body: json.loads(body)
    assert f.get("https://x.test/a", validator=validate) == b'{"products": []}'
    assert f.get("https://x.test/a", validator=validate) == b'{"products": []}'
    assert calls == [("https://x.test/a", SV)]


def test_challenge_raises_and_is_never_cached(tmp_path):
    def transport(url, profile):
        return b"<html>Verifying your connection before you proceed</html>"
    f = PoliteFetcher(tmp_path, SV, delay=0.0, transport=transport, clock=FakeClock())
    with pytest.raises(Challenged):
        f.get("https://x.test/b")
    assert list(tmp_path.glob("*.bin")) == []


def test_unfamiliar_html_is_rejected_by_validator_before_cache(tmp_path):
    f = PoliteFetcher(
        tmp_path, SV, delay=0.0,
        transport=lambda url, profile: b"<html>Temporary queue</html>",
        clock=FakeClock(),
    )
    with pytest.raises(json.JSONDecodeError):
        f.get("https://x.test/html", validator=json.loads)
    assert list(tmp_path.glob("*.bin")) == []


def test_empty_body_raises_and_is_never_cached(tmp_path):
    f = PoliteFetcher(tmp_path, SV, delay=0.0,
                      transport=lambda url, profile: b"", clock=FakeClock())
    with pytest.raises(FetchError):
        f.get("https://x.test/c")
    assert list(tmp_path.glob("*.bin")) == []


def test_transport_error_is_never_cached(tmp_path):
    def broken(url, profile):
        raise FetchError("HTTP 503")
    f = PoliteFetcher(tmp_path, SV, delay=0.0, transport=broken, clock=FakeClock())
    with pytest.raises(FetchError, match="503"):
        f.get("https://x.test/down")
    assert list(tmp_path.glob("*.bin")) == []


def test_paces_live_requests_but_not_cache_hits(tmp_path):
    clock = FakeClock()
    f = PoliteFetcher(tmp_path, SV, delay=3.0,
                      transport=lambda url, profile: b"ok", clock=clock)
    f.get("https://x.test/1")
    f.get("https://x.test/2")
    f.get("https://x.test/1")
    assert clock.slept == [pytest.approx(3.0)]


def test_namespace_forces_a_fresh_fetch(tmp_path):
    calls = []
    def transport(url, profile):
        calls.append(url)
        return b"ok"
    f = PoliteFetcher(tmp_path, SV, delay=0.0, transport=transport, clock=FakeClock())
    f.get("https://x.test/p", namespace="attempt-a")
    f.get("https://x.test/p", namespace="attempt-a")
    f.get("https://x.test/p", namespace="attempt-b")
    assert len(calls) == 2


def test_request_profile_partitions_the_cache(tmp_path):
    calls = []
    def transport(url, profile):
        calls.append(profile.locale)
        return b"ok"
    PoliteFetcher(tmp_path, SV, delay=0.0, transport=transport, clock=FakeClock()).get(
        "https://x.test/p", namespace="a"
    )
    PoliteFetcher(tmp_path, EN, delay=0.0, transport=transport, clock=FakeClock()).get(
        "https://x.test/p", namespace="a"
    )
    assert calls == ["sv-SE", "en"]
