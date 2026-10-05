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
from agent_apunts.ingestion.extract import extract_all, processed_path, read_json
from agent_apunts.ingestion.loaders import supported_extensions
from agent_apunts.ingestion.manifest import Manifest
from agent_apunts.ingestion.register import register_source
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
    for source in s.sources:
        _print_source(source.name, source.root, s)


def _print_source(source: str, root: Path, s: Settings) -> None:
    console.print()
    if not root.is_dir():
        console.print(f"[bold]{source}[/bold]  {root}  [yellow]folder not found[/yellow]")
        return
    files = find_files(root, supported_extensions())
    console.print(f"[bold]{source}[/bold]  {root}  [green]{len(files)} documents[/green]")

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
        table = Table("subject", "doc_type", "documents")
        for (subject, doc_type), n in sorted(counts.items()):
            table.add_row(subject, doc_type, str(n))
        console.print(table)
    for problem in problems:
        console.print(f"  [red]problem[/red] {problem}")


def _list(title: str, items: list, style: str = "yellow", limit: int = 20) -> None:
    if not items:
        return
    console.print(f"[{style}]{title} ({len(items)}):[/{style}]")
    for item in items[:limit]:
        text = " -> ".join(item) if isinstance(item, tuple) else str(item)
        console.print(f"  {text}")
    if len(items) > limit:
        console.print(f"  ... and {len(items) - limit} more")


@app.command()
def register(
    source: str = typer.Option("all", help="Source to scan: testing, apunts or all."),
) -> None:
    """Stage 1: give every file a content-hash ID and record it in the manifest. Safe to re-run."""
    s = _settings()
    user_id = s.user.id
    sources = s.sources if source == "all" else (s.source(source),)
    with Manifest(s.paths.manifest) as manifest:
        for src in sources:
            r = register_source(manifest, user_id, src, s)
            console.print(
                f"[bold]{src.name}[/bold]: {len(r.new)} new, {len(r.unchanged)} unchanged, "
                f"{len(r.moved)} moved, {len(r.duplicates)} duplicates, "
                f"{len(r.missing)} missing, {len(r.errors)} errors"
            )
            _list("moved or relabelled (old -> new)", r.moved, "cyan")
            _list("duplicates, skipped (file -> kept copy)", r.duplicates)
            _list("missing: in the manifest but not on disk", r.missing)
            _list("errors", r.errors, "red")


@app.command()
def extract(
    force: bool = typer.Option(False, help="Re-extract even documents that are up to date."),
) -> None:
    """Stage 2: registered documents -> data/processed/<user>/<doc_id>.json (+ thumbnails)."""
    s = _settings()
    with Manifest(s.paths.manifest) as manifest:
        r = extract_all(manifest, s.user.id, s, force=force)
    console.print(
        f"{len(r.extracted)} extracted ({r.pages} pages), {len(r.up_to_date)} up to date, "
        f"{len(r.errors)} errors"
    )
    _list("pages with no text at all (check them with inspect)", r.empty_pages)
    _list("errors", r.errors, "red")


@app.command()
def inspect(
    query: str = typer.Argument(help="Start of the doc_id, or part of the file path."),
    page: int | None = typer.Option(None, help="Show the full text of this page."),
) -> None:
    """Show what was extracted from a document, to compare it with the PDF."""
    s = _settings()
    with Manifest(s.paths.manifest) as manifest:
        matches = manifest.find(s.user.id, query)
    if not matches:
        console.print(f"[red]No document matches {query!r}.[/red] Run `register` first?")
        raise typer.Exit(1)
    if len(matches) > 1:
        console.print(f"{len(matches)} documents match {query!r}, be more specific:")
        for m in matches[:30]:
            console.print(f"  {m.doc_id[:12]}  {m.source}/{m.rel_path}")
        raise typer.Exit(1)

    record = matches[0]
    path = processed_path(s, s.user.id, record.doc_id)
    if not path.is_file():
        console.print(f"{record.rel_path} is registered but not extracted yet. Run `extract`.")
        raise typer.Exit(1)
    doc = read_json(path)

    console.print(f"[bold]{doc.source}/{doc.rel_path}[/bold]")
    console.print(f"doc_id     {doc.doc_id}")
    console.print(f"extractor  {doc.extractor}   json: {path}")
    if doc.metadata:
        console.print(f"metadata   {doc.metadata.model_dump(mode='json', exclude_none=True)}")
    console.print(f"languages  {', '.join(doc.languages) or '-'}   pages: {len(doc.pages)}")

    if page is not None:
        selected = [p for p in doc.pages if p.number == page]
        if not selected:
            console.print(f"[red]No page {page}[/red] (1-{len(doc.pages)})")
            raise typer.Exit(1)
        p = selected[0]
        console.print(f"\n[bold]Page {p.number}[/bold]  title: {p.title or '-'}")
        console.print(f"thumbnail: {s.paths.data_dir / p.thumbnail if p.thumbnail else '-'}")
        console.rule()
        console.print(p.text or "[dim](no text)[/dim]", markup=False, highlight=False)
        return

    table = Table("page", "shape", "chars", "lang", "img", "title")
    for p in doc.pages:
        shape = "landscape" if p.width > p.height else "portrait"
        flag = "[yellow]mostly image[/yellow]" if p.mostly_image else str(p.image_count)
        table.add_row(
            str(p.number), shape, str(p.char_count), p.language or "-", flag, (p.title or "")[:60]
        )
    console.print(table)
