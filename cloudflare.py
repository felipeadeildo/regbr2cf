"""Client for the Cloudflare API (create a zone, read its nameservers)."""

from typing import Self

import httpx2

BASE_URL = "https://api.cloudflare.com/client/v4"
ZONE_ALREADY_EXISTS = 1061


class Cloudflare:
    def __init__(self, token: str, account_id: str, timeout: float = 30) -> None:
        self._account_id = account_id
        self._client = httpx2.Client(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self._client.close()

    def zone_status(self, fqdn: str) -> tuple[str, list[str]] | None:
        """Return (status, nameservers) for the zone, or None if it doesn't exist.

        Status is Cloudflare's zone status, e.g. "pending" or "active".
        """
        result = self._client.get("/zones", params={"name": fqdn}).json()["result"]
        if not result:
            return None
        zone = result[0]
        return zone["status"], zone["name_servers"]

    def zone_nameservers(self, fqdn: str) -> list[str]:
        """Return the zone's assigned nameservers, creating the zone if needed."""
        response = self._client.post(
            "/zones", json={"name": fqdn, "account": {"id": self._account_id}}
        )
        data = response.json()
        if response.status_code == 200:
            return data["result"]["name_servers"]

        errors = data.get("errors", [])
        if any(e.get("code") == ZONE_ALREADY_EXISTS for e in errors):
            existing = self._client.get("/zones", params={"name": fqdn}).json()[
                "result"
            ]
            if existing:
                return existing[0]["name_servers"]
        raise RuntimeError(errors or data)
