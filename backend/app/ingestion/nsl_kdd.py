"""NSL-KDD ingestion — labelled per-connection records (no IPs/timestamps).

Primary use: training/validating the anomaly detector on real labelled traffic
(normal vs the 4 attack families). Loaded as clean DataFrames.
"""
from __future__ import annotations

import pandas as pd

from ..core.config import settings
from .schema import NSL_KDD_COLUMNS

# Canonical NSL-KDD attack-name -> family mapping (the 5-class grouping).
_ATTACK_FAMILY = {
    # DoS
    "neptune": "DoS", "back": "DoS", "land": "DoS", "pod": "DoS", "smurf": "DoS",
    "teardrop": "DoS", "mailbomb": "DoS", "apache2": "DoS", "processtable": "DoS", "udpstorm": "DoS",
    "worm": "DoS",
    # Probe
    "ipsweep": "Probe", "nmap": "Probe", "portsweep": "Probe", "satan": "Probe",
    "mscan": "Probe", "saint": "Probe",
    # R2L
    "ftp_write": "R2L", "guess_passwd": "R2L", "imap": "R2L", "multihop": "R2L",
    "phf": "R2L", "spy": "R2L", "warezclient": "R2L", "warezmaster": "R2L",
    "sendmail": "R2L", "named": "R2L", "snmpgetattack": "R2L", "snmpguess": "R2L",
    "xlock": "R2L", "xsnoop": "R2L", "httptunnel": "R2L",
    # U2R
    "buffer_overflow": "U2R", "loadmodule": "U2R", "perl": "U2R", "rootkit": "U2R",
    "ps": "U2R", "sqlattack": "U2R", "xterm": "U2R",
}


def load_nsl_kdd(path=None, limit: int | None = None) -> pd.DataFrame:
    path = path or settings.nsl_kdd_train
    df = pd.read_csv(path, header=None, names=NSL_KDD_COLUMNS, nrows=limit)
    df["is_attack"] = (df["label"] != "normal").astype(int)
    df["attack_family"] = df["label"].map(lambda x: "Normal" if x == "normal" else _ATTACK_FAMILY.get(x, "Unknown"))
    return df
