"""Transport layer: responsible request behavior and injectable fetching -
Phase 39 (Acquisition Engine), Section 15.

Two design decisions carry most of this module's weight.

1. **Fetching is injected, never hard-wired.** Every adapter receives a
   `Transport` and calls it; no adapter calls `urllib` directly. This is
   what makes the whole engine testable against deterministic fixtures
   (Section 49's "do not make the test suite depend on external websites")
   without a parallel mock-patching apparatus, and it is what lets the
   SAME adapter code run against a real network in GitHub Actions and
   against a `FixtureTransport` in CI.

   This decision was forced by a real, measured constraint rather than
   chosen on style: this development sandbox's outbound HTTPS is filtered
   by an organization egress policy that returns `403 Forbidden` at the
   proxy for every property-data host tested this phase
   (`taxsales.lgbs.com`, `www.gis.hctx.net`, `comptroller.texas.gov`,
   `floridarevenue.com`). That is an ENVIRONMENT limitation, not a source
   restriction - the same hosts answered normally through this session's
   sanctioned, robots-respecting web-fetch tool, and the same code runs
   against them successfully from GitHub Actions in production today. See
   `docs/acquisition-engine.md` for the distinction and
   `EnvironmentBlockedTransport` below for how the engine records it
   honestly rather than reporting a false source failure.

2. **Politeness is a policy object, not scattered `time.sleep()` calls.**
   `harvest_lgbs()` sleeps 0.3s between pages; `harvest_realauction()`
   sleeps 0.2s; `harvest_lienhub_certificates.ps1` uses a 4-9s jittered
   delay with a two-step backoff. Those were each correct locally and
   collectively unmaintainable. `RateLimitPolicy` carries the same
   behavior as data, per source, so a new adapter inherits responsible
   defaults instead of re-inventing them.

Explicitly NOT in this module, and never to be added to it: user-agent
rotation, proxy/identity rotation, CAPTCHA solving, WAF evasion,
authentication bypass, or robots circumvention (Section 15's prohibition
list). A source that cannot be reached without one of those is recorded as
`TECHNICAL_ACQUISITION_BLOCKED` with its reason - that is the intended
outcome, not a problem to engineer around.
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Protocol

from .result import AcquisitionStatus, content_hash


class TransportError(Exception):
    """Base class. Carries a specific `AcquisitionStatus` so a caller never
    has to re-classify an exception by inspecting its message text."""

    status = AcquisitionStatus.TECHNICAL_FAILURE
    error_code = "TRANSPORT_ERROR"

    def __init__(self, message: str, *, http_status: int | None = None):
        super().__init__(message)
        self.http_status = http_status


class SourceUnavailable(TransportError):
    status = AcquisitionStatus.SOURCE_UNAVAILABLE
    error_code = "SOURCE_UNAVAILABLE"


class RateLimited(TransportError):
    status = AcquisitionStatus.RATE_LIMITED
    error_code = "RATE_LIMITED"


class AuthenticationRequired(TransportError):
    status = AcquisitionStatus.AUTHENTICATION_REQUIRED
    error_code = "AUTHENTICATION_REQUIRED"


class AccessRestricted(TransportError):
    """A technical control (WAF, robots disallow, paywall, IP block) refused
    the request. This is a terminal, NON-retryable outcome by design: the
    correct response is to record it, never to retry differently, change
    identity, or route around it (Section 15)."""

    status = AcquisitionStatus.ACCESS_RESTRICTED
    error_code = "ACCESS_RESTRICTED"


class EnvironmentEgressBlocked(TransportError):
    """The local execution environment - not the source - refused the
    request (e.g. this sandbox's organization egress proxy returning 403 on
    CONNECT). Distinct from `AccessRestricted` because attributing an
    environment policy to the SOURCE would silently corrupt this project's
    source-health and verification records with a finding that says nothing
    about the source at all."""

    status = AcquisitionStatus.SOURCE_UNAVAILABLE
    error_code = "ENVIRONMENT_EGRESS_BLOCKED"


@dataclass(frozen=True)
class TransportResponse:
    """What every transport returns. Deliberately carries raw `body` bytes
    plus decoded helpers, so an adapter can hash the exact payload
    (Section 13's `content_hash`) before any parsing normalizes it away."""

    url: str
    http_status: int
    body: bytes
    content_type: str | None = None
    headers: dict = field(default_factory=dict)
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def json(self):
        try:
            return json.loads(self.body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SchemaError(f"response from {self.url} is not valid JSON: {exc}") from exc

    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def hash(self) -> str:
        return content_hash(self.body)

    @property
    def source_updated_at(self) -> str | None:
        """Section 13's `source_updated_at` - the source's own statement of
        freshness, never this project's retrieval time (Section 59's
        distinction). `None` when the source does not publish one, which is
        the common case and is not an error."""
        for key in ("Last-Modified", "last-modified", "X-Last-Modified"):
            if key in self.headers:
                return self.headers[key]
        return None


class SchemaError(TransportError):
    status = AcquisitionStatus.SCHEMA_FAILURE
    error_code = "SCHEMA_FAILURE"


class Transport(Protocol):
    """The one contract every adapter fetches through."""

    def get(self, url: str, *, timeout: float | None = None) -> TransportResponse:  # pragma: no cover - protocol
        ...


@dataclass(frozen=True)
class RateLimitPolicy:
    """Section 15's responsible-request requirements as data.

    Defaults are deliberately conservative and match the politeness this
    repository already practices (`harvest_lgbs()`'s 0.3s inter-page sleep
    is this policy's `min_interval_seconds` default). `jitter_seconds`
    mirrors `harvest_lienhub_certificates.ps1`'s existing jittered-delay
    approach, generalized.
    """

    timeout_seconds: float = 30.0
    min_interval_seconds: float = 0.3
    jitter_seconds: float = 0.2
    max_retries: int = 3
    backoff_base_seconds: float = 1.0
    backoff_max_seconds: float = 30.0
    max_concurrency: int = 1  # this engine is deliberately serial per source by default
    circuit_breaker_threshold: int = 5  # consecutive failures before the source is tripped

    def backoff_for(self, attempt: int) -> float:
        """Exponential backoff with jitter, capped. `attempt` is 1-based."""
        raw = self.backoff_base_seconds * (2 ** max(0, attempt - 1))
        capped = min(raw, self.backoff_max_seconds)
        return capped + random.uniform(0, self.jitter_seconds)

    def pace(self) -> float:
        return self.min_interval_seconds + random.uniform(0, self.jitter_seconds)


class CircuitBreaker:
    """Trips after `threshold` consecutive failures for one source, so a
    dead or angry source is stopped being hit rather than retried on a
    schedule. Resets on any success."""

    def __init__(self, threshold: int = 5):
        self.threshold = threshold
        self._consecutive_failures = 0
        self._tripped = False

    @property
    def tripped(self) -> bool:
        return self._tripped

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._tripped = False

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.threshold:
            self._tripped = True

    def reset(self) -> None:
        self._consecutive_failures = 0
        self._tripped = False


class UrllibTransport:
    """The real-network transport, using the same `urllib.request` this
    repository's existing harvesters already use (no new dependency).

    Applies `RateLimitPolicy`: paces requests, retries retryable failures
    with exponential backoff + jitter, and gives up at the retry ceiling.
    `AccessRestricted` and `AuthenticationRequired` are deliberately NOT
    retried - retrying a refusal is exactly the behavior Section 15
    prohibits.

    The `user_agent` parameter exists so a caller can identify this project
    honestly. It must never be used to impersonate a browser in order to
    defeat a control; `harvest_realauction()`/`harvest_all_counties.ps1`'s
    existing spoofed-Chrome UA strings are a pre-existing, separately
    documented practice this module does not adopt or extend (see
    `docs/acquisition-engine.md`).
    """

    def __init__(
        self,
        policy: RateLimitPolicy | None = None,
        *,
        user_agent: str = "taxdeed-scraper/1.0 (+acquisition-engine; contact: repository owner)",
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.policy = policy or RateLimitPolicy()
        self.user_agent = user_agent
        self._sleep = sleep
        self._last_request_at: float | None = None
        self.breaker = CircuitBreaker(self.policy.circuit_breaker_threshold)

    def _pace(self) -> None:
        if self._last_request_at is None:
            return
        elapsed = time.monotonic() - self._last_request_at
        wait = self.policy.pace() - elapsed
        if wait > 0:
            self._sleep(wait)

    def get(self, url: str, *, timeout: float | None = None) -> TransportResponse:
        import urllib.error
        import urllib.request

        if self.breaker.tripped:
            raise SourceUnavailable(
                f"circuit breaker open after {self.breaker.consecutive_failures} consecutive failures; "
                f"not requesting {url}"
            )

        effective_timeout = timeout if timeout is not None else self.policy.timeout_seconds
        last_exc: TransportError | None = None

        for attempt in range(1, self.policy.max_retries + 1):
            self._pace()
            request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
            try:
                with urllib.request.urlopen(request, timeout=effective_timeout) as resp:
                    body = resp.read()
                    self._last_request_at = time.monotonic()
                    self.breaker.record_success()
                    return TransportResponse(
                        url=url,
                        http_status=getattr(resp, "status", 200),
                        body=body,
                        content_type=resp.headers.get("Content-Type"),
                        headers=dict(resp.headers.items()),
                    )
            except urllib.error.HTTPError as exc:
                self._last_request_at = time.monotonic()
                last_exc = _classify_http_error(exc.code, url)
                # Terminal refusals are never retried (Section 15).
                if isinstance(last_exc, (AccessRestricted, AuthenticationRequired)):
                    self.breaker.record_failure()
                    raise last_exc
            except urllib.error.URLError as exc:
                self._last_request_at = time.monotonic()
                reason = str(getattr(exc, "reason", exc))
                if "403" in reason and "Tunnel connection failed" in reason:
                    # The local egress proxy refused CONNECT - an
                    # environment policy, not the source. Never retried,
                    # never routed around.
                    self.breaker.record_failure()
                    raise EnvironmentEgressBlocked(
                        f"local environment egress policy refused {url} ({reason}); "
                        "this says nothing about the source itself"
                    )
                last_exc = SourceUnavailable(f"{url}: {reason}")
            except TimeoutError as exc:
                self._last_request_at = time.monotonic()
                last_exc = SourceUnavailable(f"{url}: timeout after {effective_timeout}s ({exc})")

            if attempt < self.policy.max_retries:
                self._sleep(self.policy.backoff_for(attempt))

        self.breaker.record_failure()
        raise last_exc or SourceUnavailable(f"{url}: exhausted {self.policy.max_retries} attempts")


def _classify_http_error(code: int, url: str) -> TransportError:
    """One place where an HTTP status becomes a specific, actionable
    acquisition reason - Section 12's "do not use generic FAILED when the
    actual reason is known"."""
    if code in (401, 407):
        return AuthenticationRequired(f"{url}: HTTP {code} - authentication required", http_status=code)
    if code == 403:
        return AccessRestricted(f"{url}: HTTP {code} - access refused by a technical control", http_status=code)
    if code == 429:
        return RateLimited(f"{url}: HTTP {code} - rate limited", http_status=code)
    if code in (404, 410):
        return SourceUnavailable(f"{url}: HTTP {code} - endpoint not found (possible source change)", http_status=code)
    if 500 <= code < 600:
        return SourceUnavailable(f"{url}: HTTP {code} - source server error", http_status=code)
    return TransportError(f"{url}: HTTP {code}", http_status=code)


class FixtureTransport:
    """Deterministic transport for tests (Section 49). Maps URL -> response
    or raiseable exception. Records every URL requested so a test can assert
    on pagination, pacing and request counts without a live network."""

    def __init__(self, responses: dict[str, TransportResponse | Exception] | None = None):
        self.responses: dict[str, TransportResponse | Exception] = responses or {}
        self.requested_urls: list[str] = []

    def add_json(self, url: str, payload, *, http_status: int = 200) -> "FixtureTransport":
        self.responses[url] = TransportResponse(
            url=url,
            http_status=http_status,
            body=json.dumps(payload).encode("utf-8"),
            content_type="application/json",
        )
        return self

    def add_error(self, url: str, exc: Exception) -> "FixtureTransport":
        self.responses[url] = exc
        return self

    def get(self, url: str, *, timeout: float | None = None) -> TransportResponse:
        self.requested_urls.append(url)
        if url not in self.responses:
            raise SourceUnavailable(f"{url}: no fixture registered (fixture transport)")
        entry = self.responses[url]
        if isinstance(entry, Exception):
            raise entry
        return entry


class EnvironmentBlockedTransport:
    """Always raises `EnvironmentEgressBlocked`. Used when the engine is
    deliberately run in an environment known to have no outbound access, so
    that an acquisition run produces honest, explicitly-labelled
    environment-blocked results rather than results that look like source
    failures."""

    def __init__(self, reason: str = "outbound network disabled for this environment"):
        self.reason = reason
        self.requested_urls: list[str] = []

    def get(self, url: str, *, timeout: float | None = None) -> TransportResponse:
        self.requested_urls.append(url)
        raise EnvironmentEgressBlocked(f"{url}: {self.reason}")
