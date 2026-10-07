"""discovery.py: which files the pipeline picks up."""

from agent_apunts.ingestion.discovery import find_files


def test_find_files(tmp_path):
    for rel in [
        "b/theory/T1.PDF",  # extension is case-insensitive
        "a/exams/e.pdf",
        "a/exams/notes.txt",  # not a wanted extension
        "a/.hidden/x.pdf",  # hidden folder
        "a/exams/~$lock.pdf",  # Office/OneDrive lock file
    ]:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")

    found = find_files(tmp_path, {".pdf"})
    assert [p.relative_to(tmp_path).as_posix() for p in found] == [
        "a/exams/e.pdf",
        "b/theory/T1.PDF",
    ]


def test_missing_root_is_empty(tmp_path):
    assert find_files(tmp_path / "nope", {".pdf"}) == []
