from pathlib import Path

from myruflo.memory.embedding import cosine_similarity, embed
from myruflo.memory.store import MemoryStore


def test_embed_is_deterministic():
    a = embed("write a python function")
    b = embed("write a python function")
    assert (a == b).all()


def test_similar_text_scores_higher_than_unrelated():
    base = embed("fix the login authentication bug")
    similar = embed("fix a bug in the login authentication flow")
    unrelated = embed("bake a chocolate cake recipe")
    assert cosine_similarity(base, similar) > cosine_similarity(base, unrelated)


def test_store_add_and_search(tmp_path: Path):
    store = MemoryStore(tmp_path / "memory.db")
    store.add("patterns", "fixed a null pointer exception in the parser")
    store.add("patterns", "added unit tests for the payment service")
    store.add("other-namespace", "unrelated entry")

    hits = store.search("patterns", "null pointer bug in parser", top_k=1)
    assert len(hits) == 1
    assert "null pointer" in hits[0][1]

    assert store.count("patterns") == 2
    assert store.count("other-namespace") == 1
    assert set(store.list_namespaces()) == {"patterns", "other-namespace"}
    store.close()
