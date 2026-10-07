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
from agent_apunts.embeddings import make_embedder
from agent_apunts.ingestion.chunk import chunk_all, chunks_path, read_chunks
from agent_apunts.ingestion.discovery import find_files
from agent_apunts.ingestion.extract import extract_all, processed_path, read_json
from agent_apunts.ingestion.image_report import image_report
from agent_apunts.ingestion.index import index_all
from agent_apunts.ingestion.loaders import supported_extensions
from agent_apunts.ingestion.manifest import Manifest
from agent_apunts.ingestion.register import register_source
from agent_apunts.metadata import metadata_from_path
from agent_apunts.retrieval import search as retrieve
from agent_apunts.store import StoreError, VectorStore

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
    console.print(
        f"[bold]Embedding[/bold]  {s.embedding.provider} / {s.embedding.model}"
        f" ({s.embedding.dimension} dims)"
    )
    console.print(f"[bold]LLM[/bold]        {s.llm.provider} / {s.llm.model}")
    console.print(f"[bold]Qdrant[/bold]     {s.qdrant.url} (collection '{s.qdrant.collection}')")
    console.print(f"[bold]Ollama[/bold]     {s.ollama.url}")
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
    try:
        sources = s.sources if source == "all" else (s.source(source),)
    except KeyError as e:
        console.print(f"[red]{e.args[0]}[/red]")
        raise typer.Exit(1) from e
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
    empty = [f"{path}  page {page}" for path, page in r.empty_pages]
    _list("pages with no text at all (check them with inspect)", empty)
    _list("errors", r.errors, "red")


@app.command()
def inspect(
    query: str = typer.Argument(help="Start of the doc_id, or part of the file path."),
    page: int | None = typer.Option(None, help="Show the full text of this page."),
    chunks: bool = typer.Option(False, "--chunks", help="Show the chunks and removed boilerplate."),
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

    if chunks:
        _print_chunks(s, record.doc_id, page)
        return

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


@app.command()
def chunk(
    force: bool = typer.Option(False, help="Re-chunk even documents that are up to date."),
) -> None:
    """Stages 3+4: clean boilerplate and split pages into chunks -> data/chunks/."""
    s = _settings()
    with Manifest(s.paths.manifest) as manifest:
        r = chunk_all(manifest, s.user.id, s, force=force)
    console.print(
        f"{len(r.chunked)} chunked ({r.chunks} chunks), {len(r.up_to_date)} up to date, "
        f"{len(r.not_extracted)} not extracted yet, {len(r.errors)} errors"
    )
    # Audit for D27: the most widespread removed lines. A real sentence here = thresholds too loose.
    common = sorted(r.removed.items(), key=lambda kv: -kv[1])
    _list(
        "boilerplate removed (line -> in how many documents)",
        [f"{n:>3}  {text}" for text, n in common],
        "cyan",
    )
    _list("not extracted yet (run `extract`)", r.not_extracted)
    _list("errors", r.errors, "red")


def _print_chunks(s: Settings, doc_id: str, page: int | None) -> None:
    path = chunks_path(s, s.user.id, doc_id)
    if not path.is_file():
        console.print("Not chunked yet. Run `chunk`.")
        raise typer.Exit(1)
    doc = read_chunks(path)
    console.print(f"chunker    {doc.chunker}   chunks: {len(doc.chunks)}")
    _list("boilerplate removed (line -> times)", [f"{r.count:>3}  {r.text}" for r in doc.removed])
    selected = [c for c in doc.chunks if page is None or c.page == page]
    if page is not None:  # full text of the page's chunks, as they will be embedded
        for c in selected:
            console.rule(f"chunk {c.index} (page {c.page}, part {c.part}, {c.word_count} words)")
            console.print(c.embedding_text, markup=False, highlight=False)
        return
    table = Table("chunk", "page", "part", "words", "lang", "header")
    for c in selected:
        table.add_row(
            str(c.index), str(c.page), str(c.part), str(c.word_count), c.language or "-", c.header
        )
    console.print(table)


def _store(s: Settings) -> VectorStore:
    store = VectorStore.from_settings(s)
    try:
        store.ensure_collection()
    except StoreError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    return store


@app.command()
def index(
    force: bool = typer.Option(False, help="Re-embed even documents that are up to date."),
) -> None:
    """Stage 5: embed chunks (Ollama) and store them in Qdrant. Safe to re-run."""
    s = _settings()
    store = _store(s)
    with Manifest(s.paths.manifest) as manifest:
        r = index_all(manifest, s.user.id, s, make_embedder(s), store, force=force)
    console.print(
        f"{len(r.indexed)} indexed ({r.points} points), {len(r.up_to_date)} up to date, "
        f"{len(r.not_chunked)} not chunked yet, {len(r.errors)} errors. "
        f"Collection now holds {store.count(s.user.id)} points for {s.user.id}."
    )
    if r.stopped:
        console.print(f"[red]Stopped: {r.stopped}[/red]")
    _list("not chunked yet (run `chunk`)", r.not_chunked)
    _list("errors", r.errors, "red")
    if r.stopped:
        raise typer.Exit(1)


@app.command()
def ingest(force: bool = typer.Option(False, help="Redo every stage for every document.")) -> None:
    """All stages in order: register -> extract -> chunk -> index. Only new work is done."""
    # Called as plain functions, Typer commands get no defaults filled in: pass every argument.
    console.rule("register")
    register(source="all")
    console.rule("extract")
    extract(force=force)
    console.rule("chunk")
    chunk(force=force)
    console.rule("index")
    index(force=force)


@app.command()
def search(
    question: str = typer.Argument(help="What to look for, in any language."),
    subject: str | None = typer.Option(None, help="Only this subject (folder name)."),
    doc_type: str | None = typer.Option(None, help="Only this doc_type (theory, exams...)."),
    limit: int = typer.Option(5, help="How many chunks to return."),
) -> None:
    """Show the chunks most similar to a question (retrieval only, no LLM yet)."""
    s = _settings()
    if subject is not None and subject not in s.subjects:
        console.print(f"[red]Unknown subject {subject!r}[/red] (known: {', '.join(s.subjects)})")
        raise typer.Exit(1)
    hits = retrieve(
        question, s.user.id, make_embedder(s), _store(s), limit, subject=subject, doc_type=doc_type
    )
    if not hits:
        console.print("No chunks found. Has anything been indexed? (`agent-apunts index`)")
        return
    table = Table("score", "subject", "document", "page", "text")
    for h in hits:
        p = h.payload
        snippet = " ".join(p.get("text", "").split())[:120]
        table.add_row(
            f"{h.score:.3f}",
            p.get("subject") or "-",
            p.get("rel_path", "?"),
            str(p.get("page")),
            snippet,
        )
    console.print(table)


@app.command()
def images(top: int = typer.Option(15, help="How many documents to list.")) -> None:
    """How much content hides in images (code screenshots, diagrams)? Measures before OCR (D30)."""
    s = _settings()
    with Manifest(s.paths.manifest) as manifest:
        r = image_report(manifest, s.user.id, s)
    share = s.extraction.large_image_min_coverage
    table = Table(
        "subject", "pages", "image only", f"text + image >= {share:.0%}", "% not fully read"
    )
    for subject, st in sorted(r.by_subject.items()):
        missing = (st.image_only + st.text_and_large_image) / st.pages if st.pages else 0
        table.add_row(
            subject,
            str(st.pages),
            str(st.image_only),
            str(st.text_and_large_image),
            f"{missing:.0%}",
        )
    console.print(table)
    ranked = sorted(r.documents.items(), key=lambda kv: -len(kv[1]))[:top]
    _list(
        "documents with most text + large-image pages (open them: code? diagrams? decoration?)",
        [
            f"{len(pages):>3}  {path}  pages {', '.join(map(str, pages[:12]))}"
            for path, pages in ranked
        ],
        "cyan",
        limit=top,
    )
    if r.not_extracted:
        console.print(f"{r.not_extracted} documents not extracted yet (run `extract`).")
