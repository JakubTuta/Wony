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

# bge-small-en-v1.5 truncates at 512 tokens; ~1200 chars stays comfortably
# inside that so nothing handed to it is silently dropped.
_CHUNK_CHARS = 1200
_CHUNK_OVERLAP_CHARS = 150
# Ceiling per document. A book would otherwise fill the embeddings table and
# slow every recall (retrieval is a brute-force scan over all rows).
_MAX_DOC_CHUNKS = 400


def _get_engine() -> typing.Any:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                from fastembed import TextEmbedding
                # Deliberately CPU: bge-small is ~30MB and embeds in single-digit
                # ms on CPU, so GPU has no meaningful latency win here — and
                # fastembed's CUDA provider needs the separate fastembed-gpu
                # extra, which isn't worth the dependency for this. Pinned
                # explicitly rather than left to the default: fastembed's device
                # is AUTO, so it tried CUDA, failed, and warned on every load.
                _engine = TextEmbedding(
                    model_name="BAAI/bge-small-en-v1.5",
                    providers=["CPUExecutionProvider"],
                )
    return _engine


def embed(text: str) -> typing.List[float]:
    """Embed text → 384-dim vector. Lazy-loads the model on first call."""
    return next(iter(_get_engine().embed([text[:_CHUNK_CHARS]]))).tolist()


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


def chunk_text(text: str) -> typing.List[str]:
    """Split a document into overlapping chunks on paragraph/sentence boundaries.

    Chunks exist because bge-small only embeds the first `_CHUNK_CHARS` of what
    it is given: storing a whole document as one row meant a 50-page PDF was
    searchable by its first page and nothing else. The overlap keeps a fact that
    straddles a boundary retrievable from both sides.
    """
    text = text.strip()
    if not text:
        return []

    chunks: typing.List[str] = []
    start = 0
    while start < len(text):
        end = min(start + _CHUNK_CHARS, len(text))
        if end < len(text):
            # Prefer a paragraph break, then a sentence end, then a space —
            # cutting mid-word makes a chunk that embeds to nothing useful.
            window = text[start:end]
            for marker in ("\n\n", ". ", "\n", " "):
                cut = window.rfind(marker)
                if cut > _CHUNK_CHARS // 2:
                    end = start + cut + len(marker)
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - _CHUNK_OVERLAP_CHARS, start + 1)
    return chunks


def store_doc(path: str, text: str) -> int:
    """Embed a document as overlapping chunks and persist them.

    Returns the number of chunks queued. Embedding itself runs on a daemon
    thread so index_document answers immediately on a large file.
    """
    chunks = chunk_text(text)[:_MAX_DOC_CHUNKS]

    def _run() -> None:
        try:
            from helpers.memory_db import (
                delete_embeddings_by_key_prefix,
                upsert_embedding,
            )

            # Re-indexing replaces the file's chunks rather than layering new
            # ones on top of a stale set.
            delete_embeddings_by_key_prefix("doc", f"{path}#")
            for index, chunk in enumerate(chunks):
                upsert_embedding(
                    source_type="doc",
                    ref_id=None,
                    ref_key=f"{path}#{index}",
                    text=chunk,
                    vector=_pack(embed(chunk)),
                )
        except Exception:
            pass

    _fire(_run)
    return len(chunks)


def is_available() -> bool:
    """Return True if fastembed is installed and usable."""
    try:
        import importlib.util
        return importlib.util.find_spec("fastembed") is not None
    except Exception:
        return False
