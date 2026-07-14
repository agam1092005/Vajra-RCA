"""UNSW-NB15 ingestion — the richest real source (has real src/dst IPs, ports,
protocol, service, byte/packet counts, Unix timestamps and attack categories).

Used for: (1) live network-flow telemetry, (2) real security-alert stream from the
attack labels, (3) topology inference from real IP-to-IP communication.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pandas as pd

from ..core.config import settings
from ..core.events import Event, EventType, Severity
from .schema import UNSW_RAW_COLUMNS, infer_service_role

# attack_cat (nominal) -> severity for the alert stream. Real categories from the dataset.
_ATTACK_SEVERITY = {
    "Generic": Severity.MEDIUM,
    "Exploits": Severity.HIGH,
    "Fuzzers": Severity.LOW,
    "DoS": Severity.HIGH,
    "Reconnaissance": Severity.MEDIUM,
    "Analysis": Severity.MEDIUM,
    "Backdoor": Severity.CRITICAL,
    "Backdoors": Severity.CRITICAL,
    "Shellcode": Severity.CRITICAL,
    "Worms": Severity.CRITICAL,
}


def _parse_port(value) -> int | None:
    """UNSW records some ports as decimal, some as hex strings (e.g. '0x000b')."""
    if value is None:
        return None
    s = str(value).strip()
    if not s or s == "-":
        return None
    try:
        return int(s)
    except ValueError:
        try:
            return int(s, 16)
        except ValueError:
            return None


def load_unsw_raw(limit: int | None = 50000, files: list[Path] | None = None) -> pd.DataFrame:
    """Load real UNSW raw flows with correct column names and a parsed timestamp.

    `limit` bounds rows for a responsive live demo — every row is a REAL record,
    just a bounded slice of the millions available.
    """
    files = files or settings.unsw_raw_files
    if not files:
        raise FileNotFoundError(f"No UNSW raw files under {settings.datasets_dir/'UNSW_NB15'}")

    frames: list[pd.DataFrame] = []
    remaining = limit
    for f in files:
        nrows = remaining if remaining is not None else None
        df = pd.read_csv(
            f, header=None, names=UNSW_RAW_COLUMNS, nrows=nrows,
            dtype=str, na_values=["", " "], keep_default_na=False, low_memory=False,
        )
        frames.append(df)
        if remaining is not None:
            remaining -= len(df)
            if remaining <= 0:
                break
    df = pd.concat(frames, ignore_index=True)

    # Real numeric coercion (kept as-is; no imputation of fabricated values).
    for col in ("Stime", "Ltime"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["Label"] = pd.to_numeric(df["Label"], errors="coerce").fillna(0).astype(int)
    df["attack_cat"] = df["attack_cat"].fillna("").str.strip()
    df["sport_i"] = df["sport"].map(_parse_port)
    df["dsport_i"] = df["dsport"].map(_parse_port)
    df = df.dropna(subset=["Stime"]).sort_values("Stime").reset_index(drop=True)
    return df


def flow_to_events(row: pd.Series) -> list[Event]:
    """Map one real flow into normalized events (a flow + optionally a security alert)."""
    ts = float(row["Stime"])
    srcip, dstip = str(row["srcip"]), str(row["dstip"])
    dport = row.get("dsport_i")
    service = row.get("service")
    role = infer_service_role(dport, service)
    is_attack = int(row["Label"]) == 1
    attack_cat = (row.get("attack_cat") or "").strip()

    attrs = {
        "srcip": srcip, "dstip": dstip,
        "sport": row.get("sport_i"), "dsport": dport,
        "proto": row.get("proto"), "service": service, "state": row.get("state"),
        "sbytes": row.get("sbytes"), "dbytes": row.get("dbytes"),
        "spkts": row.get("Spkts"), "dpkts": row.get("Dpkts"),
        "sload": row.get("Sload"), "dload": row.get("Dload"),
        "role": role, "attack_cat": attack_cat, "label": int(row["Label"]),
    }

    events = [Event(
        event_type=EventType.NETWORK_FLOW, source="unsw_nb15", node=dstip, timestamp=ts,
        severity=Severity.INFO, signature=f"flow {srcip}->{dstip}:{dport or '-'} ({role})",
        description=f"{row.get('proto')} flow to {dstip}:{dport or '-'} service={service}",
        attributes=attrs,
    )]

    if is_attack:
        sev = _ATTACK_SEVERITY.get(attack_cat, Severity.MEDIUM)
        events.append(Event(
            event_type=EventType.SECURITY_ALERT, source="unsw_nb15", node=dstip, timestamp=ts,
            severity=sev, confidence=0.95,
            signature=f"{attack_cat or 'Attack'} against {dstip}",
            description=f"{attack_cat or 'Attack'} from {srcip} targeting {dstip}:{dport or '-'} ({role})",
            attributes=attrs,
        ))
    return events


def iter_flow_events(df: pd.DataFrame) -> Iterator[Event]:
    for _, row in df.iterrows():
        yield from flow_to_events(row)
