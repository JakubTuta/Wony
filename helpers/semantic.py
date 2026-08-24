"""
Semantic memory: local embeddings for long-term cross-session recall.

Uses fastembed with BAAI/bge-small-en-v1.5 (384-dim, ~30 MB, ONNX, no API key).
All data lives in the existing wony.db embeddings table — no second store.

Design:
  - Embeddings are stored as packed float32 BLOBs (struct.pack).
  - Retrieval is brute-force cosine similarity in numpy (fast enough for <100k rows).
  - Embedding calls from conversation/profile are fire-and-forget daemon threads
    so they never block the response path.
"""
import struct
import threading
import typing

import numpy as np

_engine: typing.Any = None
_engine_lock = threading.Lock()


def _get_engine() -> typing.Any:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                from fastembed import TextEmbedding
                # Deliberately CPU (no providers=): bge-small is ~30MB and embeds
                # in single-digit ms on CPU, so GPU has no meaningful latency win
                # here — and fastembed's CUDA provider needs the separate
                # fastembed-gpu extra, which isn't worth the dependency for this.
                _engine = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
    return _engine


def embed(text: str) -> typing.List[float]:
    """Embed text → 384-dim vector. Lazy-loads the model on first call."""
    return next(iter(_get_engine().embed([text[:2000]]))).tolist()


def _pack(vec: typing.List[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack(blob: bytes) -> np.ndarray:
    n = len(blob) // 4
    return np.array(struct.unpack(f"{n}f", blob), dtype=np.float32)


def retrieve(
    query: str,
    k: int = 5,
    source_types: typing.Optional[typing.List[str]] = None,
) -> typing.List[typing.Dict]:
    """
    Return top-k semantically similar items from the embeddings table.

    Each result: {"source_type", "ref_id", "ref_key", "text", "score"}.
    source_types: restrict to specific types ("turn", "fact", "doc").
    """
    from helpers.memory_db import all_embeddings

    rows = all_embeddings(source_types=source_types)
    if not rows:
        return []

    # One matmul over a stacked matrix rather than a per-row Python loop —
    # the loop was the whole cost of recall once the table grew.
    usable: typing.List[typing.Dict] = []
    vectors: typing.List[np.ndarray] = []
    dim: typing.Optional[int] = None
    for row in rows:
        try:
            vec = _unpack(row["vector"])
        except Exception:
            continue
        if dim is None:
            dim = vec.size
        elif vec.size != dim:
            continue  # stale row from a different embedding model
        usable.append(row)
        vectors.append(vec)

    if not usable:
        return []

    matrix = np.stack(vectors)
    query_vec = np.asarray(embed(query), dtype=np.float32)
    if query_vec.size != matrix.shape[1]:
        return []

    norms = np.linalg.norm(matrix, axis=1) * float(np.linalg.norm(query_vec))
    scores = np.divide(
        matrix @ query_vec, norms, out=np.zeros(len(usable), dtype=np.float32), where=norms > 0
    )

    top = np.argsort(scores)[::-1][:k]
    return [
        {
            "source_type": usable[i]["source_type"],
            "ref_id": usable[i]["ref_id"],
            "ref_key": usable[i]["ref_key"],
            "text": usable[i]["text"],
            "score": round(float(scores[i]), 4),
        }
        for i in top
    ]


# ------------------------------------------------------------------ store helpers


def _fire(fn: typing.Callable, *args: typing.Any) -> None:
    """Run a function in a daemon thread (fire-and-forget, never blocks caller)."""
    threading.Thread(target=fn, args=args, daemon=True).start()


def store_turn(turn_id: int, user_text: str, assistant_text: str) -> None:
    """Embed a conversation turn and persist it. Called async from record_turn."""
    def _run() -> None:
        try:
            from helpers.memory_db import upsert_embedding
            text = f"User: {user_text}\nAssistant: {assistant_text}"
            upsert_embedding(
                source_type="turn",
                ref_id=turn_id,
                ref_key=None,
                text=text,
                vector=_pack(embed(text)),
            )
        except Exception:
            pass
    _fire(_run)


def store_fact(key: str, value: str) -> None:
    """Embed a profile fact and persist it. Called async from Profile.set."""
    def _run() -> None:
        try:
            from helpers.memory_db import upsert_embedding
            text = f"{key}: {value}"
            upsert_embedding(
                source_type="fact",
                ref_id=None,
                ref_key=key,
                text=text,
                vector=_pack(embed(text)),
            )
        except Exception:
            pass
    _fire(_run)


def remove_fact(key: str) -> None:
    """Remove a fact's embedding. Called async from Profile.remove."""
    def _run() -> None:
        try:
            from helpers.memory_db import delete_embedding_by_ref
            delete_embedding_by_ref(source_type="fact", ref_key=key)
        except Exception:
            pass
    _fire(_run)


def store_doc(path: str, text: str) -> None:
    """Embed a document chunk and persist it. Called from index_document job."""
    def _run() -> None:
        try:
            from helpers.memory_db import upsert_embedding
            chunk = text[:2000]
            upsert_embedding(
                source_type="doc",
                ref_id=None,
                ref_key=path,
                text=chunk,
                vector=_pack(embed(chunk)),
            )
        except Exception:
            pass
    _fire(_run)


def is_available() -> bool:
    """Return True if fastembed is installed and usable."""
    try:
        import importlib.util
        return importlib.util.find_spec("fastembed") is not None
    except Exception:
        return False
