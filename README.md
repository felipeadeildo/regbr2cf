# registro.br -> Cloudflare

CLI to point [registro.br](https://registro.br) domains at Cloudflare
nameservers. For each selected domain it creates a Cloudflare zone, reads the
nameservers Cloudflare assigns, and sets them on registro.br — the manual
"update your nameservers" step, automated in bulk.

## How it works

1. Log in to registro.br (handles the emailed security code when required).
2. List your domains and let you pick which to move.
3. For each: create the zone on Cloudflare -> get its nameservers -> set them on
   registro.br.

Only domains with status **Publicado** can be edited — `Novo` (awaiting payment)
and `Registrando` (still processing) are shown but not selectable.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```sh
uv sync
cp .env.example .env   # then fill in the values
```

### Configuration (`.env`)

| Variable                | Where to get it                                                                               |
| ----------------------- | --------------------------------------------------------------------------------------------- |
| `REGISTROBR_USER`       | Your registro.br login handle (e.g. `ABCDE1`).                                                |
| `REGISTROBR_PASSWORD`   | Your registro.br password.                                                                    |
| `CLOUDFLARE_API_TOKEN`  | Cloudflare API token (**not** an `cfat_…` token) with `Account:Zone:Edit` + `Zone:Zone:Edit`. |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare account ID (Dashboard -> any domain -> Overview).                                  |

## Usage

```sh
uv run main.py
```

Pick domains by number (`1,3,5`) or `all`. Each result is printed as it
finishes; failures are logged to `data/erros-<date>.txt` (including the server
response) and don't stop the rest.

## Notes

- The registro.br login session is cached in `.session.json` and reused across
  runs, so you won't re-enter the security code every time.
- registro.br verifies the new nameservers are answering before accepting, so a
  just-created Cloudflare zone is retried for ~1 minute while it propagates.
- Nameserver changes take effect after a propagation window (registro.br shows a
  ~20 min transition, full DNS propagation up to 48h).
