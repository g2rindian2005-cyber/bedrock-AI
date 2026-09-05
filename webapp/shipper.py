"""
Writes generated events to per-date log files and streams them to CloudWatch Logs.

One log stream per calendar date. That is deliberate: PutLogEvents refuses a batch
whose events span more than 24 hours, so grouping by date makes every batch legal
by construction. Events older than 14 days are rejected by the service, so they
are dropped locally and counted instead of failing the request.

The CloudWatch agent cannot do this job - its log_stream_name supports only
{instance_id} / {hostname} / {ip_address}, with no per-file placeholder, so every
backdated file would collapse into one stream and blow the 24-hour batch rule.
"""

from __future__ import annotations

import queue
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError

from generator import LogEvent

MAX_BATCH_EVENTS = 10_000
MAX_BATCH_BYTES = 1_000_000  # service limit is 1,048,576; leave headroom
EVENT_OVERHEAD = 26  # bytes billed per event on top of the UTF-8 message
MAX_AGE_DAYS = 14  # service hard limit
SAFE_AGE_DAYS = 13


# --------------------------------------------------------------------------- #
# pure helpers - unit tested
# --------------------------------------------------------------------------- #
def is_too_old(ts_ms: int, now_ms: int, safe_days: int = SAFE_AGE_DAYS) -> bool:
    return ts_ms < now_ms - safe_days * 86_400_000


def is_too_new(ts_ms: int, now_ms: int) -> bool:
    return ts_ms > now_ms + 2 * 3_600_000 - 60_000  # 2h limit, 1 min of slack


def group_by_date(events: list[LogEvent]) -> dict[str, list[LogEvent]]:
    grouped: dict[str, list[LogEvent]] = defaultdict(list)
    for ev in events:
        grouped[ev.day].append(ev)
    for items in grouped.values():
        items.sort(key=lambda e: e.ts_ms)
    return dict(grouped)


def chunk_batch(events: list[LogEvent]) -> list[list[dict]]:
    """Chronological chunks obeying the count and byte limits."""
    chunks: list[list[dict]] = []
    cur: list[dict] = []
    size = 0
    for ev in sorted(events, key=lambda e: e.ts_ms):
        msg = ev.format()
        cost = len(msg.encode("utf-8")) + EVENT_OVERHEAD
        if cur and (len(cur) >= MAX_BATCH_EVENTS or size + cost > MAX_BATCH_BYTES):
            chunks.append(cur)
            cur, size = [], 0
        cur.append({"timestamp": ev.ts_ms, "message": msg})
        size += cost
    if cur:
        chunks.append(cur)
    return chunks


def stream_name(day: str, instance_id: str) -> str:
    return f"{instance_id}/app-{day}.log"


# --------------------------------------------------------------------------- #
# local files
# --------------------------------------------------------------------------- #
class LogFileWriter:
    """One file per date: app-YYYY-MM-DD.log, matching the timestamps inside it."""

    def __init__(self, directory: str):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def path_for(self, day: str) -> Path:
        return self.dir / f"app-{day}.log"

    def write(self, events: list[LogEvent]) -> dict[str, int]:
        counts: Counter = Counter()
        with self._lock:
            for day, items in group_by_date(events).items():
                with self.path_for(day).open("a", encoding="utf-8") as fh:
                    for ev in items:
                        fh.write(ev.format() + "\n")
                counts[day] += len(items)
        return dict(counts)

    def tail(self, day: str, limit: int = 200) -> list[str]:
        path = self.path_for(day)
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            return [ln.rstrip("\n") for ln in fh.readlines()[-limit:]]

    def day_counts(self) -> dict[str, int]:
        out = {}
        for path in sorted(self.dir.glob("app-*.log")):
            day = path.stem.replace("app-", "")
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                out[day] = sum(1 for _ in fh)
        return out


# --------------------------------------------------------------------------- #
# CloudWatch shipper
# --------------------------------------------------------------------------- #
class CloudWatchShipper:
    """Background thread. Batches per date stream and flushes on an interval."""

    def __init__(self, logs_client, log_group: str, instance_id: str,
                 retention_days: int = 14, flush_seconds: float = 2.0):
        self.logs = logs_client
        self.log_group = log_group
        self.instance_id = instance_id
        self.retention_days = retention_days
        self.flush_seconds = flush_seconds

        self._q: queue.Queue = queue.Queue(maxsize=100_000)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._known_streams: set[str] = set()
        self._lock = threading.Lock()

        self.stats = {
            "shipped": 0,
            "dropped_too_old": 0,
            "dropped_too_new": 0,
            "failed": 0,
            "batches": 0,
            "streams": [],
            "last_flush": None,
            "last_error": None,
            "enabled": True,
        }

    # ---------------- lifecycle ---------------- #
    def start(self) -> None:
        self._ensure_group()
        self._thread = threading.Thread(target=self._run, name="cw-shipper", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)

    def enqueue(self, events: list[LogEvent]) -> dict:
        now_ms = int(time.time() * 1000)
        accepted = 0
        for ev in events:
            if is_too_old(ev.ts_ms, now_ms):
                self.stats["dropped_too_old"] += 1
                continue
            if is_too_new(ev.ts_ms, now_ms):
                self.stats["dropped_too_new"] += 1
                continue
            try:
                self._q.put_nowait(ev)
                accepted += 1
            except queue.Full:
                self.stats["failed"] += 1
        return {"queued": accepted, "pending": self._q.qsize()}

    # ---------------- internals ---------------- #
    def _ensure_group(self) -> None:
        try:
            self.logs.create_log_group(logGroupName=self.log_group)
        except ClientError as err:
            if err.response["Error"]["Code"] != "ResourceAlreadyExistsException":
                self._record_error(err)
                return
        try:
            self.logs.put_retention_policy(
                logGroupName=self.log_group, retentionInDays=self.retention_days
            )
        except ClientError as err:
            self._record_error(err)

    def _ensure_stream(self, name: str) -> None:
        with self._lock:
            if name in self._known_streams:
                return
        try:
            self.logs.create_log_stream(logGroupName=self.log_group, logStreamName=name)
        except ClientError as err:
            if err.response["Error"]["Code"] != "ResourceAlreadyExistsException":
                raise
        with self._lock:
            self._known_streams.add(name)
            self.stats["streams"] = sorted(self._known_streams)

    def _run(self) -> None:
        pending: list[LogEvent] = []
        deadline = time.time() + self.flush_seconds
        while not self._stop.is_set():
            timeout = max(deadline - time.time(), 0.05)
            try:
                pending.append(self._q.get(timeout=timeout))
                # opportunistically drain
                while len(pending) < MAX_BATCH_EVENTS:
                    pending.append(self._q.get_nowait())
            except queue.Empty:
                pass

            if pending and (time.time() >= deadline or len(pending) >= MAX_BATCH_EVENTS):
                self._flush(pending)
                pending = []
                deadline = time.time() + self.flush_seconds

        if pending:
            self._flush(pending)

    def _flush(self, events: list[LogEvent]) -> None:
        for day, items in group_by_date(events).items():
            name = stream_name(day, self.instance_id)
            try:
                self._ensure_stream(name)
                for batch in chunk_batch(items):
                    resp = self.logs.put_log_events(
                        logGroupName=self.log_group, logStreamName=name, logEvents=batch
                    )
                    rejected = resp.get("rejectedLogEventsInfo") or {}
                    if "tooOldLogEventEndIndex" in rejected:
                        self.stats["dropped_too_old"] += rejected["tooOldLogEventEndIndex"]
                    if "tooNewLogEventStartIndex" in rejected:
                        self.stats["dropped_too_new"] += (
                            len(batch) - rejected["tooNewLogEventStartIndex"]
                        )
                    self.stats["shipped"] += len(batch)
                    self.stats["batches"] += 1
                self.stats["last_flush"] = datetime.now(tz=timezone.utc).isoformat(
                    timespec="seconds"
                )
                self.stats["last_error"] = None
            except (ClientError, BotoCoreError) as err:
                self.stats["failed"] += len(items)
                self._record_error(err)

    def _record_error(self, err: Exception) -> None:
        code = ""
        if isinstance(err, ClientError):
            code = err.response["Error"]["Code"] + ": "
        self.stats["last_error"] = f"{code}{err}"[:300]


class NullShipper:
    """Used when CloudWatch is unreachable or shipping is turned off."""

    def __init__(self, reason: str):
        self.stats = {
            "shipped": 0, "dropped_too_old": 0, "dropped_too_new": 0, "failed": 0,
            "batches": 0, "streams": [], "last_flush": None,
            "last_error": reason, "enabled": False,
        }

    def start(self) -> None:
        pass

    def stop(self, timeout: float = 0) -> None:
        pass

    def enqueue(self, events: list[LogEvent]) -> dict:
        return {"queued": 0, "pending": 0}
