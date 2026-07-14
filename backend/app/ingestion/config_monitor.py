"""Configuration-change monitor over a REAL git repository.

Infrastructure config lives in a real git repo (backend/var/demo-config). Every
change is a real commit with a real author, timestamp and diff. This module reads
that history into normalized CONFIG_CHANGE events and can also *apply* a change
(make a real commit) — used to drive the canonical "config change caused the
anomaly" incident. Nothing here is simulated: git is the source of truth.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Iterator

from ..core.config import settings
from ..core.events import Event, EventType, Severity

# Maps a config file to the infrastructure node it governs. This is real operator
# knowledge (a config file controls a service), used to attribute a change to a node.
_DEFAULT_MAP = {
    "routing.yaml": {"node": None, "kind": "routing_rule_update"},
    "firewall.rules": {"node": None, "kind": "firewall_policy_update"},
    "services.yaml": {"node": None, "kind": "service_config_change"},
}


def _git(repo: Path, *args: str, check: bool = True) -> str:
    res = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {res.stderr.strip()}")
    return res.stdout


class ConfigChangeMonitor:
    def __init__(self, repo: Path | None = None) -> None:
        self.repo = repo or settings.config_repo_dir

    # ---- repo lifecycle ----
    def ensure_repo(self, governed_node: str | None = None) -> None:
        """Create the real git repo with seed config if it does not yet exist."""
        if (self.repo / ".git").exists():
            return
        self.repo.mkdir(parents=True, exist_ok=True)
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "netops@vajra.local")
        _git(self.repo, "config", "user.name", "network-admin")
        cmap = {k: dict(v) for k, v in _DEFAULT_MAP.items()}
        if governed_node:
            for v in cmap.values():
                v["node"] = governed_node
        (self.repo / "routing.yaml").write_text(
            "default_route: gw-1\nroutes:\n  - dst: 0.0.0.0/0\n    via: gw-1\n    metric: 100\n")
        (self.repo / "firewall.rules").write_text(
            "# baseline\n-A INPUT -p tcp --dport 443 -j ACCEPT\n-A INPUT -p tcp --dport 53 -j ACCEPT\n")
        (self.repo / "services.yaml").write_text("services:\n  gateway:\n    upstream: db-1\n    timeout_ms: 500\n")
        (self.repo / "config_map.json").write_text(json.dumps(cmap, indent=2))
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "baseline infrastructure configuration")

    def _config_map(self) -> dict:
        p = self.repo / "config_map.json"
        return json.loads(p.read_text()) if p.exists() else {k: dict(v) for k, v in _DEFAULT_MAP.items()}

    # ---- reading history ----
    def read_changes(self, limit: int = 50) -> Iterator[Event]:
        """Yield CONFIG_CHANGE events from real commit history (newest last)."""
        if not (self.repo / ".git").exists():
            return
        cmap = self._config_map()
        log = _git(self.repo, "log", f"-{limit}", "--pretty=format:%H%x1f%an%x1f%at%x1f%s")
        for line in [l for l in log.splitlines() if l.strip()][::-1]:
            h, actor, at, subject = line.split("\x1f")
            files = _git(self.repo, "show", "--name-only", "--pretty=format:", h).split()
            for f in files:
                if f == "config_map.json":
                    continue
                meta = cmap.get(f, {"node": None, "kind": "config_change"})
                before, after = self._diff_values(h, f)
                yield Event(
                    event_type=EventType.CONFIG_CHANGE, source="config_monitor",
                    node=meta.get("node") or f, timestamp=float(at), severity=Severity.MEDIUM,
                    signature=f"{meta.get('kind','config_change')} on {meta.get('node') or f}",
                    description=f"{actor} changed {f}: {subject}",
                    attributes={
                        "commit": h[:10], "actor": actor, "file": f,
                        "change_type": meta.get("kind"), "governed_node": meta.get("node"),
                        "previous_value": before, "new_value": after, "subject": subject,
                    },
                )

    def _diff_values(self, commit: str, file: str) -> tuple[str, str]:
        try:
            diff = _git(self.repo, "show", commit, "--", file, check=False)
        except RuntimeError:
            return "", ""
        removed = [l[1:].strip() for l in diff.splitlines() if l.startswith("-") and not l.startswith("---")]
        added = [l[1:].strip() for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]
        return " | ".join(removed[:3]), " | ".join(added[:3])

    # ---- applying a real change (used by the demo/fault-injector) ----
    def apply_change(self, file: str, new_content: str, message: str,
                     actor: str = "network-admin", governed_node: str | None = None) -> Event:
        """Write `new_content` to `file` and make a real git commit; return its event."""
        self.ensure_repo()
        if governed_node:
            cmap = self._config_map()
            cmap.setdefault(file, {"kind": "config_change"})["node"] = governed_node
            (self.repo / "config_map.json").write_text(json.dumps(cmap, indent=2))
        (self.repo / file).write_text(new_content)
        _git(self.repo, "add", "-A")
        # --allow-empty guards the rare case where content is byte-identical to HEAD.
        _git(self.repo, "commit", "-q", "--allow-empty",
             "--author", f"{actor} <{actor}@vajra.local>", "-m", message)
        return list(self.read_changes(limit=1))[-1]
