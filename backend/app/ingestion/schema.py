"""Column schemas for the real datasets + entity/service inference helpers.

Column orders are taken verbatim from the datasets' own dictionaries
(UNSW: NUSW-NB15_features.csv; NSL-KDD: the canonical 43-field order).
"""
from __future__ import annotations

# UNSW-NB15 raw files (UNSW-NB15_1..4.csv) are headerless with these 49 columns,
# in the exact order documented in NUSW-NB15_features.csv.
UNSW_RAW_COLUMNS = [
    "srcip", "sport", "dstip", "dsport", "proto", "state", "dur", "sbytes", "dbytes",
    "sttl", "dttl", "sloss", "dloss", "service", "Sload", "Dload", "Spkts", "Dpkts",
    "swin", "dwin", "stcpb", "dtcpb", "smeansz", "dmeansz", "trans_depth", "res_bdy_len",
    "Sjit", "Djit", "Stime", "Ltime", "Sintpkt", "Dintpkt", "tcprtt", "synack", "ackdat",
    "is_sm_ips_ports", "ct_state_ttl", "ct_flw_http_mthd", "is_ftp_login", "ct_ftp_cmd",
    "ct_srv_src", "ct_srv_dst", "ct_dst_ltm", "ct_src_ltm", "ct_src_dport_ltm",
    "ct_dst_sport_ltm", "ct_dst_src_ltm", "attack_cat", "Label",
]

# Numeric features used by the Isolation Forest (present in both raw and the clean split).
UNSW_NUMERIC_FEATURES = [
    "dur", "sbytes", "dbytes", "sttl", "dttl", "sloss", "dloss", "Sload", "Dload",
    "Spkts", "Dpkts", "smeansz", "dmeansz", "tcprtt", "synack", "ackdat",
    "ct_srv_src", "ct_srv_dst", "ct_dst_ltm", "ct_src_ltm",
]

# NSL-KDD: 41 features + label + difficulty (43 fields, headerless).
NSL_KDD_COLUMNS = [
    "duration", "protocol_type", "service", "flag", "src_bytes", "dst_bytes", "land",
    "wrong_fragment", "urgent", "hot", "num_failed_logins", "logged_in", "num_compromised",
    "root_shell", "su_attempted", "num_root", "num_file_creations", "num_shells",
    "num_access_files", "num_outbound_cmds", "is_host_login", "is_guest_login", "count",
    "srv_count", "serror_rate", "srv_serror_rate", "rerror_rate", "srv_rerror_rate",
    "same_srv_rate", "diff_srv_rate", "srv_diff_host_rate", "dst_host_count",
    "dst_host_srv_count", "dst_host_same_srv_rate", "dst_host_diff_srv_rate",
    "dst_host_same_src_port_rate", "dst_host_srv_diff_host_rate", "dst_host_serror_rate",
    "dst_host_srv_serror_rate", "dst_host_rerror_rate", "dst_host_srv_rerror_rate",
    "label", "difficulty",
]

NSL_KDD_NUMERIC_FEATURES = [
    "duration", "src_bytes", "dst_bytes", "wrong_fragment", "urgent", "hot", "count",
    "srv_count", "serror_rate", "srv_serror_rate", "rerror_rate", "same_srv_rate",
    "diff_srv_rate", "dst_host_count", "dst_host_srv_count", "dst_host_same_srv_rate",
    "dst_host_serror_rate", "dst_host_rerror_rate",
]

# Well-known ports -> service role, used to give topology nodes a meaningful type.
PORT_ROLE = {
    53: "dns", 80: "web", 443: "web", 8080: "web", 21: "ftp", 20: "ftp-data",
    22: "ssh", 25: "smtp", 110: "pop3", 143: "imap", 3306: "database", 5432: "database",
    1433: "database", 1521: "database", 27017: "database", 6379: "cache", 11211: "cache",
    179: "router", 123: "ntp", 389: "ldap", 636: "ldap", 3389: "rdp",
}


def infer_service_role(port: int | None, service: str | None = None) -> str:
    """Best-effort role for a node/edge from real port + UNSW `service` field."""
    if service and service not in ("-", "", None):
        s = service.lower()
        if s in ("http",):
            return "web"
        if s in ("dns",):
            return "dns"
        if s in ("smtp", "pop3", "imap"):
            return "mail"
        if s in ("ftp", "ftp-data"):
            return "ftp"
        if s in ("ssh",):
            return "ssh"
        return s
    if port is not None:
        return PORT_ROLE.get(int(port), "host")
    return "host"


def to_int(value, default: int | None = None) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
