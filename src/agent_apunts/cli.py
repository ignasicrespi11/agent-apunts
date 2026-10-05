"""Command-line interface: `uv run agent-apunts --help`.

Commands are thin: they load settings, take user_id from them and call library functions,
so the same functions can later be called from FastAPI (D9) without going through the CLI.
"""

from collections import Counter
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from agent_apunts.config import ConfigError, Settings, load_settings
from agent_apunts.ingestion.discovery import find_files
from agent_apunts.metadata import metadata_from_path

app = typer.Typer(help="RAG agent over university notes.", no_args_is_help=True)
console = Console()


def _settings() -> Settings:
    try:
        return load_settings()
    except ConfigError as e:
        console.print(f"[red]Configuration error:[/red] {e}")
        raise typer.Exit(1) from e


@app.callback()
def main() -> None:
    """RAG agent over university notes."""


@app.command("config")
def show_config() -> None:
    """Show the resolved settings and how many documents each source folder holds.

    Use it on every new machine to check .env: paths must exist and the counts must match.
    Secrets (API keys) are never printed.
    """
    s = _settings()
    console.print(f"[bold]User[/bold]       {s.user.id} ({s.user.university} · {s.user.degree})")
    console.print(f"[bold]Languages[/bold]  {', '.join(s.languages)}")
    console.print(f"[bold]Embedding[/bold]  {s.embedding.model} ({s.embedding.dimension} dims)")
    console.print(f"[bold]LLM[/bold]        {s.llm.provider} / {s.llm.model}")
    console.print(f"[bold]Qdrant[/bold]     {s.qdrant.url} (collection '{s.qdrant.collection}')")
    console.print(f"[bold]Data dir[/bold]   {s.paths.data_dir}")
    console.print(f"[bold]Subjects[/bold]   {', '.join(s.subjects) or '(none)'}")
    for source, root in s.source_dirs.items():
        _print_source(source, root, s)


def _print_source(source: str, root: Path, s: Settings) -> None:
    console.print()
    if not root.is_dir():
        console.print(f"[bold]{source}[/bold]  {root}  [yellow]folder not found[/yellow]")
        return
    files = find_files(root, {".pdf"})
    console.print(f"[bold]{source}[/bold]  {root}  [green]{len(files)} PDFs[/green]")

    counts: Counter[tuple[str, str]] = Counter()
    problems: list[str] = []
    for path in files:
        try:
            meta = metadata_from_path(path, root, s)
        except ValueError as e:
            problems.append(f"{path.relative_to(root)}: {e}")
            continue
        if meta is None:
            counts[("(unorganised)", "-")] += 1
        else:
            counts[(meta.subject, meta.doc_type.value)] += 1

    if counts:
        table = Table("subject", "doc_type", "PDFs")
        for (subject, doc_type), n in sorted(counts.items()):
            table.add_row(subject, doc_type, str(n))
        console.print(table)
    for problem in problems:
        console.print(f"  [red]problem[/red] {problem}")
