"""
Log event generation.

Every browser hit produces a burst of events spread across the last N days, so a
single click populates today, yesterday, the day before, and so on.

Each calendar date gets a deterministic "character" (healthy / degraded /
incident) derived from its ordinal, so the same date always tells the same story.
That is what makes the Bedrock analysis meaningful - "the incident was on the
30th" stays true across runs.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

# CloudWatch rejects events older than 14 days, so 13 is the safe ceiling.
MAX_DAYS_BACK = 13

HEALTHY, DEGRADED, INCIDENT = "healthy", "degraded", "incident"

ROUTES = ("/api/orders", "/api/orders/8821", "/api/payments", "/api/cart", "/health")
INCIDENT_HOURS = (14, 17)  # UTC window where an incident day goes bad


@dataclass(frozen=True)
class LogEvent:
    ts_ms: int
    level: str
    message: str

    @property
    def day(self) -> str:
        return datetime.fromtimestamp(self.ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")

    def format(self) -> str:
        dt = datetime.fromtimestamp(self.ts_ms / 1000, tz=timezone.utc)
        stamp = dt.strftime("%Y-%m-%d %H:%M:%S,") + f"{dt.microsecond // 1000:03d}"
        return f"{stamp} {self.level} [orders-api] {self.message}"


def day_scenario(d: date) -> str:
    """Deterministic. A 5-day cycle, so any window of 5+ days contains an incident."""
    slot = d.toordinal() % 5
    if slot == 0:
        return INCIDENT
    if slot in (1, 3):
        return DEGRADED
    return HEALTHY


def _rid() -> str:
    return uuid.uuid4().hex[:12]


def _ok(route: str, rng: random.Random) -> tuple[str, str]:
    return "INFO", (
        f"request_id={_rid()} {rng.choice(('GET', 'POST'))} {route} 200 "
        f"latency_ms={rng.randint(18, 190)} user_id=u{rng.randint(1000, 9999)}"
    )


def _slow(route: str, rng: random.Random) -> tuple[str, str]:
    return "WARNING", (
        f"request_id={_rid()} {route} 200 slow response "
        f"latency_ms={rng.randint(900, 2600)} db_pool_wait_ms={rng.randint(400, 1600)}"
    )


def _db_error(route: str, rng: random.Random) -> tuple[str, str]:
    return "ERROR", (
        f"request_id={_rid()} {route} 500 OperationalError: could not connect to server: "
        f"Connection timed out (host=orders-db.internal port=5432 "
        f"retries={rng.randint(1, 3)})"
    )


def _pool_exhausted(route: str, rng: random.Random) -> tuple[str, str]:
    return "CRITICAL", (
        f"request_id={_rid()} {route} 503 connection pool exhausted "
        f"(size=20 in_use=20 waiters={rng.randint(24, 61)}) - shedding load"
    )


def _upstream_5xx(route: str, rng: random.Random) -> tuple[str, str]:
    return "ERROR", (
        f"request_id={_rid()} {route} 502 upstream payments-gw returned "
        f"{rng.choice((500, 502, 504))} after {rng.randint(3000, 9000)}ms"
    )


def _pick(scenario: str, hour: int, route: str, rng: random.Random) -> tuple[str, str]:
    in_window = INCIDENT_HOURS[0] <= hour < INCIDENT_HOURS[1]

    if route == "/health":  # health checks stay green; useful signal for the analyst
        return _ok(route, rng)

    if scenario == INCIDENT and in_window:
        roll = rng.random()
        if roll < 0.42:
            return _db_error(route, rng)
        if roll < 0.62:
            return _pool_exhausted(route, rng)
        if roll < 0.74:
            return _upstream_5xx(route, rng)
        if roll < 0.88:
            return _slow(route, rng)
        return _ok(route, rng)

    if scenario == DEGRADED:
        roll = rng.random()
        if roll < 0.20:
            return _slow(route, rng)
        if roll < 0.26:
            return _db_error(route, rng)
        return _ok(route, rng)

    roll = rng.random()
    if roll < 0.06:
        return _slow(route, rng)
    if roll < 0.08:
        return _upstream_5xx(route, rng)
    return _ok(route, rng)


def _timestamp_in_day(d: date, now: datetime, rng: random.Random, scenario: str) -> int | None:
    """Random instant inside day d, never in the future. None if the day has no room."""
    start = datetime.combine(d, time.min, tzinfo=timezone.utc)
    end = min(start + timedelta(days=1), now)
    if end <= start:
        return None

    # Bias incident days toward the bad window so the cluster is visible.
    if scenario == INCIDENT and rng.random() < 0.65:
        lo = start + timedelta(hours=INCIDENT_HOURS[0])
        hi = min(start + timedelta(hours=INCIDENT_HOURS[1]), end)
        if hi > lo:
            start, end = lo, hi

    span = (end - start).total_seconds()
    return int((start + timedelta(seconds=rng.uniform(0, span))).timestamp() * 1000)


def generate_visit(
    route: str,
    days_back: int = 7,
    per_day: tuple[int, int] = (3, 8),
    now: datetime | None = None,
    rng: random.Random | None = None,
) -> list[LogEvent]:
    """One browser hit -> events on each of the last `days_back` days (today included)."""
    rng = rng or random.Random()
    now = now or datetime.now(tz=timezone.utc)
    days_back = max(1, min(days_back, MAX_DAYS_BACK))

    events: list[LogEvent] = []
    for offset in range(days_back):
        d = (now - timedelta(days=offset)).date()
        scenario = day_scenario(d)
        for _ in range(rng.randint(*per_day)):
            ts = _timestamp_in_day(d, now, rng, scenario)
            if ts is None:
                continue
            hour = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).hour
            hit_route = route if rng.random() < 0.5 else rng.choice(ROUTES)
            level, msg = _pick(scenario, hour, hit_route, rng)
            events.append(LogEvent(ts_ms=ts, level=level, message=msg))

    events.sort(key=lambda e: e.ts_ms)
    return events


def window_summary(days_back: int, now: datetime | None = None) -> list[dict]:
    """What the UI timeline renders before any traffic exists."""
    now = now or datetime.now(tz=timezone.utc)
    out = []
    for offset in range(max(1, min(days_back, MAX_DAYS_BACK))):
        d = (now - timedelta(days=offset)).date()
        out.append(
            {
                "date": d.isoformat(),
                "days_ago": offset,
                "scenario": day_scenario(d),
                "label": "today" if offset == 0 else ("yesterday" if offset == 1 else f"-{offset}d"),
            }
        )
    return out
