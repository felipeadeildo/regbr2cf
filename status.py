"""Per-domain migration status, cross-checking registro.br and Cloudflare.

Results are cached in .status-cache.json. A "migrated" verdict is terminal and
reused forever; anything still in flight is re-checked after a short TTL.
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path

from cloudflare import Cloudflare
from registrobr import RegistroBR

CACHE_FILE = Path(__file__).parent / ".status-cache.json"
TTL_SECONDS = 3600  # re-check non-terminal states after an hour
CLOUDFLARE_NS_SUFFIX = ".ns.cloudflare.com"

MIGRATED = "migrated"  # registro.br points at Cloudflare and the zone is active


@dataclass
class Status:
    verdict: str  # human-readable state
    reg_ns: list[str]  # nameservers set on registro.br
    cf_status: str | None  # Cloudflare zone status, or None if no zone

    @property
    def terminal(self) -> bool:
        return self.verdict == MIGRATED


def _verdict(reg_ns: list[str], cf: tuple[str, list[str]] | None) -> str:
    on_cloudflare_ns = bool(reg_ns) and all(
        ns.endswith(CLOUDFLARE_NS_SUFFIX) for ns in reg_ns
    )
    if cf is None:
        return "on cloudflare NS (no zone)" if on_cloudflare_ns else "not on cloudflare"
    cf_status, _ = cf
    if on_cloudflare_ns and cf_status == "active":
        return MIGRATED
    if on_cloudflare_ns:
        return f"zone {cf_status}, NS set"
    return f"zone {cf_status}, NS not set"


class StatusChecker:
    def __init__(self, reg: RegistroBR, cf: Cloudflare) -> None:
        self._reg = reg
        self._cf = cf
        self._cache: dict[str, dict] = {}
        if CACHE_FILE.exists():
            self._cache = json.loads(CACHE_FILE.read_text())

    def _save(self) -> None:
        CACHE_FILE.parent.mkdir(exist_ok=True)
        CACHE_FILE.write_text(json.dumps(self._cache, indent=2))

    def _fresh(self, fqdn: str) -> Status | None:
        entry = self._cache.get(fqdn)
        if not entry:
            return None
        if entry["verdict"] == MIGRATED:  # terminal — never re-check
            return Status(entry["verdict"], entry["reg_ns"], entry["cf_status"])
        if time.time() - entry["checked_at"] < TTL_SECONDS:
            return Status(entry["verdict"], entry["reg_ns"], entry["cf_status"])
        return None

    def check(self, fqdn: str) -> Status:
        """Return the domain's status, using the cache when still valid."""
        cached = self._fresh(fqdn)
        if cached:
            return cached
        reg_ns = self._reg.nameservers(fqdn)
        cf = self._cf.zone_status(fqdn)
        status = Status(_verdict(reg_ns, cf), reg_ns, cf[0] if cf else None)
        self._cache[fqdn] = {
            "verdict": status.verdict,
            "reg_ns": status.reg_ns,
            "cf_status": status.cf_status,
            "checked_at": time.time(),
        }
        self._save()
        return status

    def mark_migrated(self, fqdn: str, cf_nameservers: list[str]) -> None:
        """Record a just-completed migration so it isn't re-checked next run."""
        self._cache[fqdn] = {
            "verdict": MIGRATED,
            "reg_ns": cf_nameservers,
            "cf_status": "active",
            "checked_at": time.time(),
        }
        self._save()
