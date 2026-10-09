"""Command-line interface: `uv run agent-apunts --help`.

Commands are thin: they load settings, take user_id from them and call library functions,
so the same functions can later be called from FastAPI (D9) without going through the CLI.
"""

from collections import Counter
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table

from agent_apunts import detection, doctor, evaluation
from agent_apunts.config import ConfigError, Settings, load_settings
from agent_apunts.embeddings import EmbeddingError, make_embedder
from agent_apunts.ingestion import prune as pruning
from agent_apunts.ingestion.chunk import chunk_all, chunks_path, read_chunks
from agent_apunts.ingestion.discovery import find_files
from agent_apunts.ingestion.extract import extract_all, processed_path, read_json
from agent_apunts.ingestion.image_report import image_report
from agent_apunts.ingestion.index import index_all
from agent_apunts.ingestion.loaders import supported_extensions
from agent_apunts.ingestion.manifest import Manifest
from agent_apunts.ingestion.register import RegisterReport, register_source
from agent_apunts.llm import LLMError, make_llm
from agent_apunts.metadata import metadata_from_path
from agent_apunts.rag import ask as answer_question
from agent_apunts.rag import log_answer
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


def _register_all(
    s: Settings, manifest: Manifest, sources, write: bool = True
) -> dict[str, RegisterReport]:
    reports = {}
    for src in sources:
        r = register_source(manifest, s.user.id, src, s, write=write)
        reports[src.name] = r
        if not r.scanned:
            console.print(f"[bold]{src.name}[/bold]: [yellow]folder not found: {src.root}[/yellow]")
            continue
        console.print(
            f"[bold]{src.name}[/bold]: {len(r.new)} new, {len(r.unchanged)} unchanged, "
            f"{len(r.moved)} moved, {len(r.duplicates)} duplicates, "
            f"{len(r.missing)} missing, {len(r.errors)} errors"
        )
        _list("moved or relabelled (old -> new)", r.moved, "cyan")
        _list("duplicates, skipped (file -> kept copy)", r.duplicates)
        _list("missing: in the manifest but not on disk (`prune` removes them)", r.missing)
        _list("errors", r.errors, "red")
    return reports


@app.command()
def register(
    source: str = typer.Option("all", help="Source to scan: testing, apunts or all."),
) -> None:
    """Stage 1: give every file a content-hash ID and record it in the manifest. Safe to re-run."""
    s = _settings()
    try:
        sources = s.sources if source == "all" else (s.source(source),)
    except KeyError as e:
        console.print(f"[red]{e.args[0]}[/red]")
        raise typer.Exit(1) from e
    with Manifest(s.paths.manifest) as manifest:
        _register_all(s, manifest, sources)


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

    # Location and metadata from the manifest (source of truth: a moved file keeps its extraction).
    console.print(f"[bold]{record.source}/{record.rel_path}[/bold]")
    console.print(f"doc_id     {doc.doc_id}")
    console.print(f"extractor  {doc.extractor}   json: {path}")
    if record.metadata:
        console.print(f"metadata   {record.metadata.model_dump(mode='json', exclude_none=True)}")
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


def _with_hybrid(s: Settings, hybrid: bool | None) -> Settings:
    """Settings with retrieval.hybrid overridden by a --hybrid/--no-hybrid flag, if given."""
    if hybrid is None:
        return s
    return s.model_copy(update={"retrieval": s.retrieval.model_copy(update={"hybrid": hybrid})})


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
    progress = Progress(
        TextColumn("index"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("documents"),
        TimeElapsedColumn(),
        TextColumn("{task.description}"),
        console=console,
        transient=True,  # the summary below replaces the bar when done
    )
    task = progress.add_task("", total=None)

    def on_progress(done: int, total: int, rel_path: str) -> None:
        progress.update(task, completed=done, total=total, description=rel_path)

    with progress, Manifest(s.paths.manifest) as manifest:
        r = index_all(
            manifest, s.user.id, s, make_embedder(s), store, force=force, on_progress=on_progress
        )
    console.print(
        f"{len(r.indexed)} indexed ({r.points} points), {len(r.up_to_date)} up to date, "
        f"{len(r.payload_only)} moved/relabelled (payload only), "
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
    """All stages: register -> prune -> extract -> chunk -> index. Only new work is done."""
    # Called as plain functions, Typer commands get no defaults filled in: pass every argument.
    s = _settings()
    console.rule("register")
    with Manifest(s.paths.manifest) as manifest:
        scans = _register_all(s, manifest, s.sources)
        console.rule("prune")
        _prune(s, manifest, scans, dry_run=False, strict=False)
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
    hybrid: bool | None = typer.Option(
        None, "--hybrid/--no-hybrid", help="Fuse keyword search (D37). Default: settings.yaml."
    ),
) -> None:
    """Show the chunks most similar to a question (retrieval only, no LLM)."""
    s = _settings()
    if subject is not None and subject not in s.subjects:
        console.print(f"[red]Unknown subject {subject!r}[/red] (known: {', '.join(s.subjects)})")
        raise typer.Exit(1)
    use_hybrid = s.retrieval.hybrid if hybrid is None else hybrid
    try:
        hits = retrieve(
            question,
            s.user.id,
            make_embedder(s),
            _store(s),
            limit,
            subject=subject,
            doc_type=doc_type,
            hybrid=use_hybrid,
        )
    except EmbeddingError as e:  # found on the real run: a traceback instead of the fix
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
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


@app.command()
def ask(
    question: str = typer.Argument(help="Your question, in Catalan, Spanish or English."),
    subject: str | None = typer.Option(None, help="Only this subject (folder name)."),
    doc_type: str | None = typer.Option(None, help="Only this doc_type (theory, exams...)."),
    hybrid: bool | None = typer.Option(
        None, "--hybrid/--no-hybrid", help="Fuse keyword search (D37). Default: settings.yaml."
    ),
) -> None:
    """Answer from your notes only, citing document and page; abstain if they don't say (D32)."""
    s = _with_hybrid(_settings(), hybrid)
    if subject is not None and subject not in s.subjects:
        console.print(f"[red]Unknown subject {subject!r}[/red] (known: {', '.join(s.subjects)})")
        raise typer.Exit(1)
    try:
        answer = answer_question(
            question, s.user.id, s, make_embedder(s), _store(s), make_llm(s), subject, doc_type
        )
    except (EmbeddingError, LLMError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    log_answer(answer, s.paths.logs_dir)

    console.print(answer.answer, markup=False, highlight=False)
    if answer.abstained:
        # max, not the first source: with hybrid search the first isn't always the most similar.
        best = f"{max(s.score for s in answer.sources):.3f}" if answer.sources else "-"
        console.print(
            f"[dim](abstained: {answer.reason}; best score {best}, "
            f"min_score {s.retrieval.min_score})[/dim]"
        )
    elif answer.uncited:
        console.print("[yellow]Warning: the answer cites no source. Don't trust it.[/yellow]")
    console.print()
    table = Table("n", "cited", "score", "document", "page")
    for src in answer.sources:
        table.add_row(
            f"[{src.number}]",
            "yes" if src.number in answer.cited else "",
            f"{src.score:.3f}",
            src.rel_path,
            str(src.page),
        )
    console.print(table)
    if answer.model:
        console.print(f"[dim]{answer.model}, {answer.latency_ms / 1000:.1f} s[/dim]")


@app.command("eval")
def evaluate(
    file: str = typer.Option("eval/golden.yaml", help="Golden set (see eval/README.md)."),
    k: int = typer.Option(5, help="How many chunks to retrieve per question."),
    filter_subject: bool = typer.Option(False, help="Also filter each query by its subject."),
    sweep: bool = typer.Option(False, help="Try min_score thresholds to calibrate abstention."),
    show_failures: bool = typer.Option(True, help="List questions whose answer was not found."),
    hybrid: bool | None = typer.Option(
        None, "--hybrid/--no-hybrid", help="Fuse keyword search (D37). Default: settings.yaml."
    ),
    answers: bool = typer.Option(
        False,
        help="Also run `ask` on every question with the local LLM (slow): abstention and "
        "citation quality.",
    ),
) -> None:
    """Measure retrieval on the golden set: hit@k, MRR, per language/subject/tag (D34)."""
    s = _with_hybrid(_settings(), hybrid)
    console.print(
        f"[dim]retrieval: {'hybrid (dense + keywords)' if s.retrieval.hybrid else 'dense'}[/dim]"
    )
    path = Path(file) if Path(file).is_absolute() else s.paths.project_root / file
    if not path.is_file():
        console.print(
            f"[red]{path} not found.[/red] Copy eval/golden.example.yaml and write yours."
        )
        raise typer.Exit(1)
    try:
        golden = evaluation.load_golden(path)
    except ValueError as e:  # includes pydantic.ValidationError
        console.print(f"[red]Invalid golden set:[/red] {e}")
        raise typer.Exit(1) from e

    with Manifest(s.paths.manifest) as manifest:
        known = {r.rel_path for r in manifest.documents(s.user.id)}
    unknown = sorted({e.document for q in golden.questions for e in q.expected} - known)
    _list("expected documents not in the manifest (typo? not registered?)", unknown, "red")

    try:
        results = evaluation.run_questions(
            golden, s.user.id, make_embedder(s), _store(s), k, filter_subject, s.retrieval.hybrid
        )
    except EmbeddingError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e

    ks = tuple(sorted({1, 3, k}))
    overall = evaluation.metrics(results, ks)
    groups = evaluation.breakdown(results, ks)
    gate = evaluation.abstention(results, s.retrieval.min_score)

    table = Table("group", "value", "questions", *[f"hit@{x}" for x in ks], "MRR")
    table.add_row(
        "all",
        "",
        str(overall.questions),
        *[f"{overall.hit_at[x]:.0%}" for x in ks],
        f"{overall.mrr:.3f}",
    )
    for name, by in groups.items():
        for value, m in by.items():
            if m.questions:
                table.add_row(
                    name,
                    value,
                    str(m.questions),
                    *[f"{m.hit_at[x]:.0%}" for x in ks],
                    f"{m.mrr:.3f}",
                )
    console.print(table)
    console.print(
        f"Abstention at min_score={gate.threshold}: correct on unanswerable "
        f"{_pct(gate.correct_abstention)}, false on answerable {_pct(gate.false_abstention)}"
    )
    if sweep:
        rows = evaluation.sweep(results)
        sweep_table = Table("min_score", "correct abstention", "false abstention", "balanced")
        for row in rows:
            sweep_table.add_row(
                f"{row.threshold:.2f}",
                _pct(row.correct_abstention),
                _pct(row.false_abstention),
                _pct(row.balanced),
            )
        console.print(sweep_table)
    if show_failures:
        failures = [r for r in results if r.answerable and (r.rank is None or r.rank > k)]
        _list(
            f"answerable questions with no correct chunk in the top {k}",
            [f"{r.id}: got {r.top[0] if r.top else 'nothing'}" for r in failures],
        )
    summary = {
        "overall": overall.model_dump(),
        "breakdown": {n: {v: m.model_dump() for v, m in by.items()} for n, by in groups.items()},
        "abstention": gate.model_dump(),
        "k": k,
        "filter_subject": filter_subject,
        "hybrid": s.retrieval.hybrid,
        "golden": str(path),
    }
    saved = evaluation.save_run(s, results, summary, s.paths.eval_dir)
    console.print(f"[dim]Saved to {saved}[/dim]")
    if answers:
        _evaluate_answers(s, golden, filter_subject)


def _evaluate_answers(s: Settings, golden, filter_subject: bool) -> None:
    console.rule(f"answers ({s.llm.model}, {len(golden.questions)} questions)")

    def progress(r) -> None:
        state = f"abstained ({r.reason})" if r.abstained else f"cited {len(r.cited)}"
        console.print(f"  {r.id}: {state}, {r.latency_ms / 1000:.1f} s")

    try:
        results = evaluation.run_answers(
            golden, s.user.id, s, make_embedder(s), _store(s), make_llm(s), filter_subject, progress
        )
    except (EmbeddingError, LLMError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    m = evaluation.answer_metrics(results)
    console.print(
        f"Abstention accuracy {m.abstention_accuracy:.0%} "
        f"({m.false_abstentions} answerable refused, "
        f"{m.missed_abstentions} unanswerable answered)\n"
        f"Citations: {m.citation_hit:.0%} of answers cite an expected page; "
        f"{m.citation_precision:.0%} of citations are expected pages; {m.uncited} uncited answers\n"
        f"Mean latency {m.mean_latency_s} s"
    )
    saved = evaluation.save_run(s, results, m.model_dump(), s.paths.eval_dir, kind="answers")
    console.print(f"[dim]Saved to {saved}[/dim]")


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.0%}"


@app.command()
def prune(
    dry_run: bool = typer.Option(False, help="Only list what would be removed."),
) -> None:
    """Forget documents whose PDF was deleted or replaced (D35). Never touches the PDFs.

    Runs `register` on every source first: only content seen nowhere is pruned."""
    s = _settings()
    with Manifest(s.paths.manifest) as manifest:
        # A dry run scans without writing: the manifest is left exactly as it was.
        scans = _register_all(s, manifest, s.sources, write=not dry_run)
        _prune(s, manifest, scans, dry_run=dry_run, strict=True)


def _prune(
    s: Settings, manifest: Manifest, scans: dict[str, RegisterReport], dry_run: bool, strict: bool
) -> None:
    orphans = pruning.find_orphans(manifest, s.user.id, s, scans)
    for name in orphans.blocked_sources:
        console.print(
            f"[yellow]{name}: some files could not be read (see errors above); nothing is pruned "
            "there until they can.[/yellow]"
        )
    for name in orphans.skipped_sources:
        console.print(
            f"[yellow]{name}: folder not found, its documents are kept as they are.[/yellow]"
        )
    paths = [r.rel_path for r in orphans.documents]
    if not paths:
        console.print("Nothing to prune.")
        return
    if dry_run:
        _list("would be removed (file deleted or replaced)", paths)
        return
    try:
        store = _store(s)
    except typer.Exit:
        if strict:
            raise
        console.print(
            "[yellow]Prune skipped (Qdrant not reachable); the other stages go on.[/yellow]"
        )
        return
    pruning.remove(manifest, s.user.id, s, store, orphans.documents)
    _list("removed (manifest, JSON, thumbnails, Qdrant points)", paths)


def _document_vectors(s: Settings):
    """(records, doc_id -> document vector, doc_id -> first page text) for chunked documents.

    Vectors from header-free chunk samples (D36), shared by `detect` and `duplicates`."""
    texts: dict[str, list[str]] = {}
    first_pages: dict[str, str] = {}
    with Manifest(s.paths.manifest) as manifest:
        records = manifest.documents(s.user.id)
    for record in records:
        chunk_file = chunks_path(s, s.user.id, record.doc_id)
        page_file = processed_path(s, s.user.id, record.doc_id)
        if not chunk_file.is_file() or not page_file.is_file():
            continue
        chunk_texts = [c.text for c in read_chunks(chunk_file).chunks]
        if chunk_texts:
            texts[record.doc_id] = detection.sample_texts(chunk_texts, s.detection.sample_chunks)
        pages = read_json(page_file).pages
        first_pages[record.doc_id] = pages[0].text if pages else ""
    if not texts:
        console.print("No chunked documents yet. Run `ingest` (or register/extract/chunk) first.")
        raise typer.Exit(1)
    try:
        cache = s.paths.data_dir / "detection" / s.user.id / "document_vectors.json"
        vectors = detection.document_vectors(texts, make_embedder(s), cache)
    except EmbeddingError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    return records, vectors, first_pages


@app.command()
def detect(
    evaluate: bool = typer.Option(False, help="Measure accuracy leave-one-out on labelled PDFs."),
) -> None:
    """Suggest subject / doc_type / year for unorganised PDFs (D18, D36). Changes nothing."""
    s = _settings()
    records, vectors, first_pages = _document_vectors(s)

    labelled = [r for r in records if r.metadata is not None]
    margin = s.detection.min_margin
    if evaluate:
        r = detection.evaluate_leave_one_out(labelled, vectors, first_pages, margin)
        console.print(
            f"{r.documents} labelled documents, each predicted as if it were unorganised:\n"
            f"  subject correct:  {r.rate(r.subject_correct, r.documents):.0%}\n"
            f"  doc_type correct: {r.rate(r.doc_type_correct, r.documents):.0%} (keyword rules)\n"
            f"  confident (margin >= {margin}): {r.rate(r.confident, r.documents):.0%} of "
            f"documents, subject correct in {r.rate(r.confident_correct, r.confident):.0%} of those"
        )
        table = Table("true subject", "predicted", "documents")
        for (truth, guess), n in sorted(r.confusion.items()):
            table.add_row(truth, guess, str(n), style=None if truth == guess else "red")
        console.print(table)
        _list(
            "wrong subject (path: true -> predicted)",
            [f"{p}: {t} -> {g}" for p, t, g in r.mistakes],
        )
        return

    unorganised = [r for r in records if r.metadata is None and r.doc_id in vectors]
    if not unorganised:
        console.print("Every document already has metadata from its folders. Nothing to detect.")
        return
    labels = {r.doc_id: r.metadata.subject for r in labelled}
    centroids = detection.subject_centroids(vectors, labels)
    table = Table("document", "subject", "margin", "confident", "doc_type", "year")
    for record in unorganised:
        d = detection.detect(
            record, vectors[record.doc_id], first_pages.get(record.doc_id, ""), centroids, margin
        )
        table.add_row(
            d.rel_path,
            d.subject or "-",
            f"{d.margin:.3f}",
            "yes" if d.confident else "[yellow]no: confirm[/yellow]",
            f"{d.doc_type.value} ({d.doc_type_source})",
            d.academic_year or "-",
        )
    console.print(table)
    console.print(
        "[dim]Suggestions only. To accept one, move the PDF to apunts/<subject>/<doc_type>/ "
        "and run `ingest` (folders win, D18).[/dim]"
    )


@app.command("doctor")
def run_doctor() -> None:
    """Check everything a machine needs (folders, Ollama + models, Qdrant) and pipeline progress."""
    s = _settings()
    checks = doctor.check_sources(s) + doctor.check_ollama(s) + doctor.check_qdrant(s)
    table = Table("", "check", "status", "fix")
    for c in checks:
        table.add_row("[green]ok[/green]" if c.ok else "[red]!![/red]", c.name, c.detail, c.fix)
    console.print(table)
    counts = doctor.pipeline_counts(s, s.user.id)
    console.print(
        "Pipeline for "
        + s.user.id
        + ": "
        + ", ".join(f"{n} {stage}" for stage, n in counts.items())
    )
    if not all(c.ok for c in checks):
        raise typer.Exit(1)


@app.command()
def duplicates(
    min_similarity: float = typer.Option(0.9, help="Report document pairs at least this similar."),
) -> None:
    """Near-duplicate documents (translations, with/without solutions...): measure before D19."""
    s = _settings()
    records, vectors, _ = _document_vectors(s)
    paths = {r.doc_id: r.rel_path for r in records}
    pairs = detection.similar_pairs(vectors, min_similarity)
    if not pairs:
        console.print(f"No document pairs with similarity >= {min_similarity}.")
        return
    table = Table("similarity", "document", "near-duplicate of")
    for a, b, similarity in pairs:
        table.add_row(f"{similarity:.3f}", paths[a], paths[b])
    console.print(table)
    groups = detection.group_pairs(pairs)
    console.print(
        f"{len(pairs)} pairs in {len(groups)} groups. Open a few: translation? solutions? "
        "same deck twice? This decides how D19 collapses them in search results."
    )
