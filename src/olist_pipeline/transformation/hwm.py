"""High-watermark (HWM) state file management for incremental loads.

The state file (a small JSON in S3) records what each transformation layer has
already processed. Every successful run reads it at start, applies the
``ingestion_hwm`` as a filter on the input, then atomically updates it with
the new max ``ingested_at`` from the batch.

Atomic updates use S3's conditional PUT: ``If-Match`` with the previously
read ETag for updates, ``If-None-Match: *`` for the very first write. If two
runs collide, only one succeeds; the loser raises
:class:`StateConflictError` so the caller can fail fast rather than silently
overwrite a concurrent update.

State file format follows ADR-0006::

    {
      "layer": "staging",
      "table": "orders",
      "last_run": {
        "run_id": "2026-05-22T06:00:00Z-run42",
        "completed_at": "2026-05-22T06:14:32Z",
        "status": "success"
      },
      "watermarks": {
        "ingestion_hwm": "2026-05-22T00:00:00Z",
        "business_hwm": "2018-04-30T23:59:59Z"
      },
      "stats": {
        "rows_processed": 8421,
        "rows_late_arriving": 0,
        "partitions_touched": ["year=2018/month=04"]
      }
    }
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from botocore.exceptions import ClientError

from olist_pipeline.core.aws import S3Client

# Sentinel watermark for the very first run, before any data has been
# processed. Any real ``ingested_at`` value will exceed this.
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class StateConflictError(Exception):
    """Raised when the HWM state file was modified between read and write.

    Indicates a concurrent writer overwrote the state file. The caller should
    abort the current run rather than retry blindly: the read filter is now
    stale and re-running would produce incorrect results.
    """


@dataclass(frozen=True)
class Watermarks:
    """The two watermarks tracked at each layer transition (ADR-0006).

    ``ingestion_hwm`` advances monotonically on successful runs. ``business_hwm``
    may NOT advance if a batch contains late-arriving rows -- the gap between
    them is the late-arriving signal.
    """

    ingestion_hwm: datetime
    business_hwm: datetime

    @classmethod
    def initial(cls) -> Watermarks:
        """Both watermarks set to epoch -- nothing has been processed yet."""
        return cls(ingestion_hwm=EPOCH, business_hwm=EPOCH)


@dataclass(frozen=True)
class LastRun:
    """Audit fields for the most recent run of this layer/table."""

    run_id: str
    completed_at: datetime
    status: str  # "success" | "failure"


@dataclass
class RunStats:
    """Per-run row counts and touched partitions, kept for monitoring."""

    rows_processed: int = 0
    rows_late_arriving: int = 0
    partitions_touched: list[str] = field(default_factory=list)


@dataclass
class HwmState:
    """Complete state document for one ``(layer, table)`` pair."""

    layer: str
    table: str
    watermarks: Watermarks
    last_run: LastRun | None = None
    stats: RunStats = field(default_factory=RunStats)

    @classmethod
    def initial(cls, layer: str, table: str) -> HwmState:
        """Return a fresh state used before the first run of a (layer, table)."""
        return cls(layer=layer, table=table, watermarks=Watermarks.initial())


@dataclass(frozen=True)
class HwmSnapshot:
    """Result of :func:`read_state`: the parsed state plus the ETag at read time.

    Pass ``etag`` back to :func:`write_state` so the conditional PUT can detect
    concurrent writers. For a state file that did not exist (first ever run),
    ``etag`` is ``None`` and :func:`write_state` will use ``If-None-Match: *``
    instead of ``If-Match``.
    """

    state: HwmState
    etag: str | None


def read_state(
    s3: S3Client,
    bucket: str,
    key: str,
    layer: str,
    table: str,
) -> HwmSnapshot:
    """Read the HWM state file from S3.

    Returns the initial (epoch-based) state if the file does not exist --
    the first run of a layer has no predecessor to read from.
    """
    try:
        response = s3.get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in {"NoSuchKey", "404"}:
            return HwmSnapshot(state=HwmState.initial(layer, table), etag=None)
        raise

    payload = json.loads(response["Body"].read().decode("utf-8"))
    etag = _normalize_etag(response["ETag"])
    return HwmSnapshot(state=_deserialize(payload), etag=etag)


def write_state(
    s3: S3Client,
    bucket: str,
    key: str,
    state: HwmState,
    expected_etag: str | None,
    tagging: str | None = None,
) -> str:
    """Atomically write the state file. Returns the new ETag on success.

    Conditional semantics:

    * ``expected_etag is None`` -- write only if the object does not yet
      exist (``If-None-Match: *``). Used on the very first write.
    * ``expected_etag`` is set -- write only if the current ETag matches
      (``If-Match``). Catches concurrent updates.

    Raises :class:`StateConflictError` when the precondition fails.
    """
    body = json.dumps(_serialize(state), indent=2).encode("utf-8")
    put_kwargs: dict[str, Any] = {
        "Bucket": bucket,
        "Key": key,
        "Body": body,
        "ContentType": "application/json",
    }
    if expected_etag is None:
        put_kwargs["IfNoneMatch"] = "*"
    else:
        put_kwargs["IfMatch"] = expected_etag
    if tagging:
        put_kwargs["Tagging"] = tagging

    try:
        response = s3.put_object(**put_kwargs)
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in {"PreconditionFailed", "ConditionalRequestConflict"}:
            raise StateConflictError(
                f"state file s3://{bucket}/{key} was modified by another writer"
            ) from exc
        raise

    return _normalize_etag(response["ETag"])


def _serialize(state: HwmState) -> dict[str, Any]:
    """Render an HwmState as the ADR-0006 JSON shape."""
    document: dict[str, Any] = {
        "layer": state.layer,
        "table": state.table,
        "watermarks": {
            "ingestion_hwm": _to_iso_z(state.watermarks.ingestion_hwm),
            "business_hwm": _to_iso_z(state.watermarks.business_hwm),
        },
        "stats": {
            "rows_processed": state.stats.rows_processed,
            "rows_late_arriving": state.stats.rows_late_arriving,
            "partitions_touched": list(state.stats.partitions_touched),
        },
    }
    if state.last_run is not None:
        document["last_run"] = {
            "run_id": state.last_run.run_id,
            "completed_at": _to_iso_z(state.last_run.completed_at),
            "status": state.last_run.status,
        }
    return document


def _deserialize(document: dict[str, Any]) -> HwmState:
    """Parse the ADR-0006 JSON shape back into an HwmState."""
    watermarks_payload = document["watermarks"]
    watermarks = Watermarks(
        ingestion_hwm=_parse_iso(watermarks_payload["ingestion_hwm"]),
        business_hwm=_parse_iso(watermarks_payload["business_hwm"]),
    )

    last_run: LastRun | None = None
    last_run_payload = document.get("last_run")
    if isinstance(last_run_payload, dict):
        last_run = LastRun(
            run_id=last_run_payload["run_id"],
            completed_at=_parse_iso(last_run_payload["completed_at"]),
            status=last_run_payload["status"],
        )

    stats_payload = document.get("stats") or {}
    stats = RunStats(
        rows_processed=int(stats_payload.get("rows_processed", 0)),
        rows_late_arriving=int(stats_payload.get("rows_late_arriving", 0)),
        partitions_touched=list(stats_payload.get("partitions_touched", [])),
    )

    return HwmState(
        layer=document["layer"],
        table=document["table"],
        watermarks=watermarks,
        last_run=last_run,
        stats=stats,
    )


def _to_iso_z(dt: datetime) -> str:
    """Serialize a UTC datetime in ISO 8601 with a ``Z`` suffix."""
    return dt.isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 timestamp (optionally with a ``Z`` suffix) as UTC."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _normalize_etag(raw: str) -> str:
    """Strip the surrounding quotes that S3 wraps around ETags."""
    return raw.strip('"')
