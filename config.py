"""Typed environment config. Loads .env, then exposes the values as constants."""

import os

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"missing required env var: {name} (see .env.example)")
    return value.strip()  # guard against accidental whitespace/newlines in .env


REGISTROBR_USER: str = _require("REGISTROBR_USER")
REGISTROBR_PASSWORD: str = _require("REGISTROBR_PASSWORD")
CLOUDFLARE_API_TOKEN: str = _require("CLOUDFLARE_API_TOKEN")
CLOUDFLARE_ACCOUNT_ID: str = _require("CLOUDFLARE_ACCOUNT_ID")
