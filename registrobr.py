"""Client for the registro.br account API (login, domains, nameservers).

The login session (cookies) is persisted to a local file and reused across runs.
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Self

import httpx2

BASE_URL = "https://registro.br/v2/ajax"
SESSION_FILE = Path(__file__).parent / ".session.json"

# registro.br only accepts nameserver changes for domains in this status.
EDITABLE_STATUS = "Publicado"

# Delays (seconds) between attempts while the new nameservers aren't answering.
RETRY_DELAYS = (0, 10, 20, 30)


class ChallengeRequired(Exception):
    """Login needs the security code emailed to the user."""


class DomainLocked(Exception):
    """The domain can't be edited now (payment pending or already in transition)."""

    def __init__(self, fqdn: str, response: str) -> None:
        super().__init__(f"{fqdn}: domain locked (payment pending or in transition)")
        self.response = response


class NameserversUnreachable(Exception):
    """registro.br couldn't resolve the nameservers (they aren't answering yet)."""

    def __init__(self, fqdn: str, response: str) -> None:
        super().__init__(f"{fqdn}: nameservers not answering after retries")
        self.response = response


@dataclass
class Domain:
    fqdn: str
    status: str

    @property
    def editable(self) -> bool:
        return self.status == EDITABLE_STATUS


class RegistroBR:
    def __init__(self, timeout: float = 30) -> None:
        self._client = httpx2.Client(
            base_url=BASE_URL,
            follow_redirects=True,
            timeout=timeout,
            event_hooks={"request": [self._send_xsrf_header]},
        )
        self._user: str | None = None
        self._login_body: dict | None = None
        self._load_session()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self._client.close()

    # -- session ---------------------------------------------------------------

    def _send_xsrf_header(self, request: httpx2.Request) -> None:
        """Echo the XSRF-TOKEN cookie as a header, which the API requires."""
        token = self._client.cookies.get("XSRF-TOKEN")
        if token:
            request.headers["X-XSRF-Token"] = token

    def _load_session(self) -> None:
        if not SESSION_FILE.exists():
            return
        for name, value in json.loads(SESSION_FILE.read_text()).items():
            self._client.cookies.set(name, value, domain="registro.br")

    def _save_session(self) -> None:
        SESSION_FILE.write_text(json.dumps(dict(self._client.cookies)))

    def is_logged_in(self) -> bool:
        return self._client.get("/user/resources").status_code == 200

    # -- auth ------------------------------------------------------------------

    def login(self, user: str, password: str) -> None:
        """Authenticate, reusing a saved session when still valid.

        Raises ChallengeRequired when an emailed security code is needed;
        call submit_challenge() with the code to finish.
        """
        self._user = user
        if self.is_logged_in():
            return

        # An initial request seeds the XSRF-TOKEN cookie the API expects.
        self._client.get("/ping")
        token = self._client.get("/checklogin?v=2").json()["token"]
        self._login_body = {
            "Password": password,
            "OTP": "",
            "challenge": "",
            "recaptcha": "",
            "service": "turnstile",
            "token": token,
        }
        r = self._client.post(f"/user/login/{user}", json=self._login_body)
        if r.status_code == 200:
            self._save_session()
            return
        messages = r.json().get("messages", [{}])
        if messages[0].get("code") == "login:challenge-required":
            raise ChallengeRequired
        raise RuntimeError(f"login failed: {messages}")

    def submit_challenge(self, code: str) -> None:
        if not self._user or not self._login_body:
            raise RuntimeError("call login() first")
        # The emailed code may contain spaces or a trailing newline.
        self._login_body["challenge"] = "".join(filter(str.isdigit, code))
        r = self._client.post(f"/user/otp/login/{self._user}", json=self._login_body)
        if r.status_code != 200:
            raise RuntimeError(f"code rejected: {r.json().get('messages')}")
        self._save_session()

    # -- domains ---------------------------------------------------------------

    def domains(self) -> list[Domain]:
        data = self._client.get("/domains").json()["domains"]
        return [Domain(d["FQDN"], d["Status"]) for d in data]

    def nameservers(self, fqdn: str) -> list[str]:
        """Current nameservers configured for the domain."""
        hosts = self._client.get(f"/domain/{fqdn}").json().get("Hosts", [])
        return [h["Hostname"] for h in hosts if h.get("Hostname")]

    def set_nameservers(self, fqdn: str, nameservers: list[str]) -> None:
        """Point a domain at the given nameservers (up to 6).

        registro.br verifies the nameservers are answering before accepting, so
        a just-created zone is retried a few times before giving up.
        """
        hosts = [{"Hostname": ns, "IPv4": "", "IPv6": ""} for ns in nameservers]
        hosts += [{"Hostname": ""}] * (6 - len(hosts))
        body = {"hosts": hosts, "dsSet": [{"keyTag": None, "digest": ""}] * 2}

        last_response = ""
        for delay in RETRY_DELAYS:
            if delay:
                time.sleep(delay)
            r = self._client.post(f"/domain/{fqdn}/dns", json=body)
            if r.status_code == 200:
                return
            last_response = r.text
            codes = {m.get("code", "") for m in r.json().get("messages", [])}
            if "unauthorized-operation" in codes:
                raise DomainLocked(fqdn, r.text)
            if not any(c.startswith("hoststatus:") for c in codes):
                raise RuntimeError(f"set_nameservers {r.status_code}: {r.text}")
        raise NameserversUnreachable(fqdn, last_response)
