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
from status import MIGRATED, Status, StatusChecker

console = Console()

STATUS_COLOR = {"Publicado": "green", "Novo": "cyan", "Registrando": "yellow"}
LOG_DIR = Path(__file__).parent / "data"


def verdict_color(verdict: str) -> str:
    if verdict == MIGRATED:
        return "green"
    if verdict.startswith("not on") or "not set" in verdict:
        return "red"
    return "yellow"


def log_error(fqdn: str, error: Exception) -> Path:
    """Append a failure (with the server response, if any) to data/erros-<date>.txt."""
    LOG_DIR.mkdir(exist_ok=True)
    now = datetime.now().astimezone()
    path = LOG_DIR / f"erros-{now:%Y-%m-%d}.txt"
    response = getattr(error, "response", "")
    with path.open("a") as f:
        f.write(f"{now:%H:%M:%S}\t{fqdn}\t{error}\t{response}\n")
    return path


def pick(domains: list[Domain], statuses: dict[str, Status]) -> list[Domain]:
    """Show domains with migration status; editable, non-migrated ones are selectable."""
    table = Table("#", "Domain", "Status", "Migration", "registro.br NS")
    selectable: list[Domain] = []
    for d in domains:
        st = statuses[d.fqdn]
        color = STATUS_COLOR.get(d.status, "white")
        # Already-migrated or non-editable domains aren't offered for migration.
        if d.editable and not st.terminal:
            selectable.append(d)
            num = str(len(selectable))
        else:
            num = "[dim]-[/]"
        table.add_row(
            num,
            d.fqdn,
            f"[{color}]{d.status}[/]",
            f"[{verdict_color(st.verdict)}]{st.verdict}[/]",
            ", ".join(st.reg_ns) or "[dim]—[/]",
        )
    console.print(table)

    if not selectable:
        console.print("[green]Nothing to migrate — all done or not editable.[/]")
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
        try:
            with console.status("Logging in..."):
                reg.login(config.REGISTROBR_USER, config.REGISTROBR_PASSWORD)
        except ChallengeRequired:
            console.print("[yellow]A security code was emailed to you.[/]")
            reg.submit_challenge(Prompt.ask("Email code"))

        domains = reg.domains()
        if not domains:
            console.print("[red]No domains found.[/]")
            sys.exit(1)

        checker = StatusChecker(reg, cf)
        statuses: dict[str, Status] = {}
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("Checking status...", total=len(domains))
            for d in domains:
                progress.update(task, description=f"Checking [cyan]{d.fqdn}[/]")
                statuses[d.fqdn] = checker.check(d.fqdn)
                progress.advance(task)

        chosen = pick(domains, statuses)
        if not chosen:
            return

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
                    checker.mark_migrated(d.fqdn, ns)
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
