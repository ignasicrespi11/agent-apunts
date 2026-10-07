"""chunking.py: size decides (D26)."""

from agent_apunts.ingestion.chunking import count_words, split_text


def _words(n, word="w"):
    return " ".join(f"{word}{i}" for i in range(n))


def test_small_page_is_one_chunk():
    text = "Patrons de disseny\n\nUn patró és una solució reutilitzable."
    assert split_text(text, max_words=450, target_words=350) == [text]


def test_empty_page_gives_no_chunks():
    assert split_text("   \n ", max_words=450, target_words=350) == []


def test_dense_page_is_split_at_paragraphs():
    paragraphs = [_words(200, f"p{i}_") for i in range(4)]  # 800 words in 4 paragraphs
    chunks = split_text("\n\n".join(paragraphs), max_words=450, target_words=350)
    assert len(chunks) == 2
    assert chunks[0] == "\n\n".join(paragraphs[:2])  # boundaries fall between paragraphs
    assert all(count_words(c) <= 450 for c in chunks)


def test_no_words_lost_or_duplicated():
    text = "\n\n".join(_words(n, f"p{n}_") for n in (120, 300, 90, 410, 30, 260))
    chunks = split_text(text, max_words=450, target_words=350)
    assert " ".join(chunks).split() == text.split()
    assert all(count_words(c) <= 450 for c in chunks)


def test_huge_paragraph_falls_back_to_lines_then_words():
    lines = "\n".join(_words(100, f"l{i}_") for i in range(6))  # one paragraph, 600 words
    one_line = _words(1000, "x")  # no line breaks at all
    for text in (lines, one_line):
        chunks = split_text(text, max_words=450, target_words=350)
        assert len(chunks) >= 2
        assert all(count_words(c) <= 450 for c in chunks)
        assert " ".join(chunks).split() == text.split()


def test_tiny_tail_is_glued_to_previous_chunk():
    text = _words(400, "a") + "\n\n" + _words(100, "b") + "\n\n" + "Final line."
    chunks = split_text(text, max_words=450, target_words=350)
    assert chunks[-1].endswith("Final line.")
    assert not any(c == "Final line." for c in chunks)
