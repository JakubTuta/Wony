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


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a)) * float(np.linalg.norm(b))
    return float(np.dot(a, b) / denom) if denom > 0 else 0.0


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

    query_vec = np.array(embed(query), dtype=np.float32)
    scored: typing.List[typing.Tuple[float, typing.Dict]] = []

    for row in rows:
        try:
            vec = _unpack(row["vector"])
            score = _cosine(query_vec, vec)
            scored.append((score, {
                "source_type": row["source_type"],
                "ref_id": row["ref_id"],
                "ref_key": row["ref_key"],
                "text": row["text"],
                "score": round(score, 4),
            }))
        except Exception:
            pass

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:k]]


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
