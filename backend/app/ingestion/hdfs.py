"""HDFS log ingestion — real parsed system logs (Date/Time/Level/Component/Content)
with block-level anomaly ground truth joined from anomaly_label.csv.

Uses the pre-parsed HDFS_2k structured sample so we never load the 23GB raw logs.
Emits LOG events, and SECURITY_ALERT/ANOMALY-style signals for error templates or
blocks labelled Anomaly.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterator

import pandas as pd

from ..core.config import settings
from ..core.events import Event, EventType, Severity

_BLOCK_RE = re.compile(r"(blk_-?\d+)")
_ERROR_HINTS = ("exception", "error", "fail", "interrupted", "corrupt", "not served")


def _parse_ts(date: str, time_: str) -> float:
    """HDFS uses 'yymmdd' date + 'HHMMSS' time (e.g. 081109 203615)."""
    try:
        dt = datetime.strptime(f"{int(date):06d}{int(time_):06d}", "%y%m%d%H%M%S")
        return dt.replace(tzinfo=timezone.utc).timestamp()
    except (ValueError, TypeError):
        return 0.0


def load_hdfs_labels() -> dict[str, str]:
    path = settings.hdfs_anomaly_labels
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    return dict(zip(df["BlockId"].astype(str), df["Label"].astype(str)))


def load_hdfs_structured(limit: int | None = None) -> pd.DataFrame:
    df = pd.read_csv(settings.hdfs_structured, nrows=limit)
    df["ts"] = df.apply(lambda r: _parse_ts(r["Date"], r["Time"]), axis=1)
    df["block_id"] = df["Content"].map(lambda c: (_BLOCK_RE.search(str(c)) or [None])[0]
                                       if _BLOCK_RE.search(str(c)) else None)
    return df


def iter_log_events(df: pd.DataFrame, labels: dict[str, str] | None = None) -> Iterator[Event]:
    labels = labels or {}
    for _, r in df.iterrows():
        content = str(r["Content"])
        level = str(r.get("Level", "INFO"))
        component = str(r.get("Component", "hdfs"))
        block = r.get("block_id")
        is_error = level.upper() in ("ERROR", "WARN", "FATAL") or any(h in content.lower() for h in _ERROR_HINTS)
        block_label = labels.get(str(block)) if block else None

        sev = Severity.INFO
        etype = EventType.LOG
        if is_error:
            sev = Severity.MEDIUM
        if block_label == "Anomaly":
            sev = Severity.HIGH
            etype = EventType.SECURITY_ALERT

        yield Event(
            event_type=etype, source="hdfs", node=component, timestamp=float(r["ts"]),
            severity=sev,
            signature=f"{r.get('EventId','')}: {r.get('EventTemplate','')[:60]}",
            description=content[:200],
            attributes={
                "level": level, "component": component, "pid": r.get("Pid"),
                "event_id": r.get("EventId"), "template": r.get("EventTemplate"),
                "block_id": block, "block_label": block_label, "is_error": is_error,
            },
        )
