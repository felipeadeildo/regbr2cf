"""CLI: point registro.br domains at Cloudflare nameservers.

Log in to registro.br, list domains, pick some, and for each: create a
Cloudflare zone, read its assigned nameservers, and set them on registro.br.
"""

import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt
from rich.table import Table

import config
from cloudflare import Cloudflare
from registrobr import ChallengeRequired, Domain, RegistroBR

console = Console()

STATUS_COLOR = {"Publicado": "green", "Novo": "cyan", "Registrando": "yellow"}
LOG_DIR = Path(__file__).parent / "data"


def log_error(fqdn: str, error: Exception) -> Path:
    """Append a failure (with the server response, if any) to data/erros-<date>.txt."""
    LOG_DIR.mkdir(exist_ok=True)
    now = datetime.now().astimezone()
    path = LOG_DIR / f"erros-{now:%Y-%m-%d}.txt"
    response = getattr(error, "response", "")
    with path.open("a") as f:
        f.write(f"{now:%H:%M:%S}\t{fqdn}\t{error}\t{response}\n")
    return path


def pick(domains: list[Domain]) -> list[Domain]:
    """Show all domains with status; only editable ones are selectable."""
    table = Table("#", "Domain", "Status")
    selectable: list[Domain] = []
    for d in domains:
        color = STATUS_COLOR.get(d.status, "white")
        if d.editable:
            selectable.append(d)
            num = str(len(selectable))
        else:
            num = "[dim]-[/]"
        table.add_row(num, d.fqdn, f"[{color}]{d.status}[/]")
    console.print(table)

    if not selectable:
        console.print("[red]No editable domains (all still processing).[/]")
        return []
    sel = Prompt.ask("Domains to move ('all' or e.g. 1,3,5)", default="all").strip()
    if sel.lower() == "all":
        return selectable
    idx = [int(x) for x in sel.replace(" ", "").split(",") if x]
    return [selectable[i - 1] for i in idx]


def main() -> None:
    with (
        RegistroBR() as reg,
        Cloudflare(config.CLOUDFLARE_API_TOKEN, config.CLOUDFLARE_ACCOUNT_ID) as cf,
    ):
        console.print("Logging in...")
        try:
            reg.login(config.REGISTROBR_USER, config.REGISTROBR_PASSWORD)
        except ChallengeRequired:
            console.print("[yellow]A security code was emailed to you.[/]")
            reg.submit_challenge(Prompt.ask("Email code"))

        domains = reg.domains()
        if not domains:
            console.print("[red]No domains found.[/]")
            sys.exit(1)

        chosen = pick(domains)
        ok = 0
        failed = 0
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Moving domains...", total=len(chosen))
            for d in chosen:
                progress.update(task, description=f"[cyan]{d.fqdn}[/]")
                try:
                    ns = cf.zone_nameservers(d.fqdn)
                    reg.set_nameservers(d.fqdn, ns)
                    ok += 1
                    progress.console.print(f"[green]✓[/] {d.fqdn} → {', '.join(ns)}")
                except Exception as e:  # noqa: BLE001 — log and keep going
                    failed += 1
                    log_error(d.fqdn, e)
                    progress.console.print(f"[red]✗[/] {d.fqdn}: {e}")
                progress.advance(task)

        console.print(f"\n[green]{ok} ok[/] · [red]{failed} failed[/]")
        if failed:
            console.print(f"Errors logged to [dim]{LOG_DIR}/erros-*.txt[/]")


if __name__ == "__main__":
    main()
