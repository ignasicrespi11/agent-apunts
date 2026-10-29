"""sparse.py: BM25-style keyword vectors without a model (D37)."""

from agent_apunts.sparse import encode_document, encode_query, tokens


def test_tokens_normalise_accents_and_case():
    assert tokens("Memòria CAU, TLB i un 2 de 1024") == [
        "memoria",
        "cau",
        "tlb",
        "un",
        "2",
        "de",
        "1024",
    ]


def test_same_word_same_index_on_every_run():
    assert (
        encode_query("TLB").indices == encode_query("tlb").indices == encode_query("TLB?").indices
    )


def test_bm25_saturation_and_length():
    once = encode_document("tlb " + "filler " * 10, avg_len=10)
    many = encode_document("tlb " * 5 + "filler " * 6, avg_len=10)
    tlb = encode_query("tlb").indices[0]
    w_once = once.values[once.indices.index(tlb)]
    w_many = many.values[many.indices.index(tlb)]
    assert w_once < w_many < 5 * w_once  # more repetitions weigh more, but saturate
    short = encode_document("tlb cache", avg_len=10)
    long = encode_document("tlb cache " + "filler " * 40, avg_len=10)
    assert short.values[short.indices.index(tlb)] > long.values[long.indices.index(tlb)]


def test_empty_text():
    assert encode_document("", 10).indices == [] and encode_query("?").indices == []
