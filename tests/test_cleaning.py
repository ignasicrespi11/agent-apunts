"""cleaning.py: per-document boilerplate removal (D27)."""

from agent_apunts.ingestion.cleaning import PAGE_NUMBER_LABEL, clean_pages


def _clean(texts):
    return clean_pages(texts, min_share=0.5, min_pages=3, max_chars=100)


TOPICS = ["Cache", "Pipeline", "Branch prediction", "Virtual memory", "TLB", "DMA"]


def test_repeated_footer_is_removed():
    texts = [f"{t}\nDisseny de Software  ·  UAB" for t in TOPICS]
    texts[1] = texts[1].upper()  # case and spacing don't matter
    result = _clean(texts)
    assert result.pages[0] == "Cache"
    assert result.removed == {"Disseny de Software · UAB": 6}


def test_numbered_headings_are_kept():
    # "Exercici 1", "Exercici 2"... are different lines: masking digits would delete them all.
    texts = [f"Exercici {i}\n{t}" for i, t in enumerate(TOPICS, start=1)]
    assert _clean(texts).pages == texts


def test_line_on_few_pages_is_kept():
    texts = ["Cache\nshared line", "Memory\nshared line", "Bus", "Disk", "CPU", "GPU"]
    result = _clean(texts)  # 2 of 6 pages: below 50%
    assert result.pages[0] == "Cache\nshared line"
    assert not result.removed


def test_short_documents_are_not_cleaned():
    texts = ["Same title\nA", "Same title\nB"]  # 2 pages < min_pages=3
    assert _clean(texts).pages == texts


def test_long_repeated_lines_are_kept():
    sentence = "This definition is long and important and repeated on every page. " * 2
    texts = [f"{sentence}\nPage text {i}" for i in range(5)]  # > max_chars: not boilerplate
    assert all(sentence.strip() in page for page in _clean(texts).pages)


def test_page_numbers_only_at_top_or_bottom():
    texts = [
        "Title\nalpha\n1",  # page 1 numbered 1 at the bottom: removed
        "2\nTitle two\nbeta",  # page 2 numbered 2 at the top: removed
        "Table\n3\nvalue",  # "3" in the middle (a table cell): kept
        "Cover-offset\ngamma\n2",  # page 4 printed as "2" (unnumbered cover): removed
        "Exam\nresult\n1024",  # 1024 is not this page's number: kept
    ]
    result = _clean(texts)
    assert result.pages[0] == "Title\nalpha"
    assert result.pages[1] == "Title two\nbeta"
    assert result.pages[2] == "Table\n3\nvalue"
    assert result.pages[3] == "Cover-offset\ngamma"
    assert result.pages[4] == "Exam\nresult\n1024"
    assert result.removed[PAGE_NUMBER_LABEL] == 3


def test_blank_runs_are_collapsed():
    texts = ["A\n\nFooter\n\n\nB", "C\nFooter", "D\nFooter"]
    assert _clean(texts).pages[0] == "A\n\nB"


def test_numbers_repeated_in_tables_are_kept():
    texts = [f"{t}\n0\n1\n0" for t in TOPICS]  # binary table values on every page
    assert _clean(texts).pages == texts


def test_repeated_short_label_is_removed_and_reported():
    # Known trade-off (D27): a label repeated on most pages is treated as boilerplate. It shows up
    # in the audit list, which is how a wrong removal gets noticed.
    texts = [f"Exercise {i}\nSolution:\nanswer {i * 7}" for i in range(1, 5)]
    result = _clean(texts)
    assert "Solution:" in result.removed
