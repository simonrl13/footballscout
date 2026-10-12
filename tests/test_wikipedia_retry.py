"""The fetcher's HTTP helper with a fake connection and a fake clock: no network, no real waiting."""
import io
import json
import socket
import urllib.error

import pytest

from scout.text import wikipedia as wp

OK = {"query": {"pages": []}}


class Fake:
    """Plays a script of outcomes (exceptions or JSON payloads); sleeping advances a fake clock."""

    def __init__(self, *script):
        self.script, self.calls, self.sleeps, self.now = list(script), 0, [], 0.0

    def open(self, req, timeout):
        assert timeout == 60 and "ScoutResearchBot" in req.get_header("User-agent")
        self.calls += 1
        step = self.script.pop(0) if self.script else self.forever
        if isinstance(step, BaseException):
            raise step
        return io.BytesIO(json.dumps(step).encode())

    def sleep(self, s):
        self.sleeps.append(s)
        self.now += s

    def clock(self):
        return self.now

    def get(self):
        return wp._get(wp.API, {"action": "query"}, _open=self.open, _sleep=self.sleep, _clock=self.clock)


def http(code, retry_after=None):
    return urllib.error.HTTPError(wp.API, code, "err", {"Retry-After": retry_after} if retry_after else {}, None)


def test_transient_failures_are_retried_with_exponential_backoff_then_succeed():
    dns = urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed"))
    fake = Fake(dns, TimeoutError("timed out"), ConnectionResetError("reset"), http(503), {"error": {"code": "maxlag"}}, OK)
    assert fake.get() == OK
    assert fake.calls == 6
    assert fake.sleeps == [5, 10, 20, 40, 80, wp.PAUSE]  # backoff, then the normal polite pause


def test_retry_after_is_honoured():
    fake = Fake(http(429, retry_after="90"), OK)
    assert fake.get() == OK and fake.sleeps[0] == 90


@pytest.mark.parametrize("code", [400, 403, 404])
def test_other_4xx_errors_are_not_retried(code):
    fake = Fake(http(code), OK)
    with pytest.raises(urllib.error.HTTPError):
        fake.get()
    assert fake.calls == 1 and fake.sleeps == []


def test_gives_up_with_a_clear_message_after_about_ten_minutes():
    fake = Fake()
    fake.forever = urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed"))
    with pytest.raises(wp.FetchGaveUp, match="rerun the same command to resume") as e:
        fake.get()
    assert "getaddrinfo failed" in str(e.value)
    assert sum(fake.sleeps) <= wp.RETRY_BUDGET and max(fake.sleeps) == wp.MAX_WAIT
    assert sum(fake.sleeps) > wp.RETRY_BUDGET - wp.MAX_WAIT  # it really tried for most of the budget
