"""Knowledge base: chunking, tokenisation and lightweight retrieval.

The original product uses a vector/knowledge-base backed AI reply.  This clone
implements a dependency-free lexical retriever that works well for Chinese:
CJK runs are indexed as character bigrams, Latin text as lowercase words, and
chunks are ranked with a TF-IDF-style score.
"""

from __future__ import annotations

import math
import re
from collections import Counter

CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
WORD_RE = re.compile(r"[a-zA-Z0-9_]+")
PARA_RE = re.compile(r"\n\s*\n")
MAX_CHUNK = 400
OVERLAP = 60
MAX_SEARCH_CHUNKS = 3000


def tokenize(text: str) -> list[str]:
    text = (text or "").lower()
    tokens: list[str] = []
    for m in WORD_RE.finditer(text):
        tokens.append(m.group())
    for m in CJK_RE.finditer(text):
        run = m.group()
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
    return tokens


def split_chunks(text: str, size: int = MAX_CHUNK, overlap: int = OVERLAP) -> list[str]:
    text = (text or "").replace("\r\n", "\n").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    current = ""
    for para in PARA_RE.split(text):
        para = para.strip()
        if not para:
            continue
        if len(para) > size:
            if current:
                chunks.append(current)
                current = ""
            step = max(1, size - overlap)
            for start in range(0, len(para), step):
                piece = para[start:start + size].strip()
                if piece:
                    chunks.append(piece)
        elif len(current) + len(para) + 2 <= size:
            current = (current + "\n\n" + para).strip()
        else:
            if current:
                chunks.append(current)
            current = para
    if current:
        chunks.append(current)
    return [c for c in chunks if c.strip()]


def reindex_document(conn, doc_id: int) -> int:
    row = conn.execute("SELECT * FROM knowledge_documents WHERE id=?", (doc_id,)).fetchone()
    if not row:
        return 0
    conn.execute("DELETE FROM knowledge_chunks WHERE doc_id=?", (doc_id,))
    pieces = split_chunks(row["content"])
    for piece in pieces:
        conn.execute(
            "INSERT INTO knowledge_chunks(doc_id, kb_id, content, created_at) VALUES(?,?,?,?)",
            (doc_id, row["kb_id"], piece, row["updated_at"]),
        )
    conn.commit()
    return len(pieces)


def search(conn, query: str, kb_id: int | None = None, limit: int = 3, owner_id: int | None = None) -> list[dict]:
    q_tokens = list(dict.fromkeys(tokenize(query)))
    if not q_tokens:
        return []
    sql = (
        "SELECT c.id, c.doc_id, c.kb_id, c.content, d.title "
        "FROM knowledge_chunks c JOIN knowledge_documents d ON d.id=c.doc_id "
        "JOIN knowledge_bases b ON b.id=c.kb_id WHERE b.enabled=1"
    )
    args: list = []
    if kb_id:
        sql += " AND c.kb_id=?"
        args.append(kb_id)
    if owner_id:
        sql += " AND b.owner_id=?"
        args.append(owner_id)
    sql += " ORDER BY c.id LIMIT ?"
    args.append(MAX_SEARCH_CHUNKS)
    rows = conn.execute(sql, args).fetchall()
    if not rows:
        return []

    counts = [Counter(tokenize(r["content"] + " " + r["title"])) for r in rows]
    df: Counter = Counter()
    q_set = set(q_tokens)
    for cnt in counts:
        for token in q_set:
            if token in cnt:
                df[token] += 1
    total = len(rows)
    scored = []
    for row, cnt in zip(rows, counts):
        score = 0.0
        for token in q_tokens:
            tf = cnt.get(token, 0)
            if tf:
                score += (1.0 + math.log(tf)) * math.log((total + 1.0) / (df[token] + 0.5))
        if score > 0:
            scored.append({
                "chunk_id": row["id"], "doc_id": row["doc_id"], "kb_id": row["kb_id"],
                "title": row["title"], "content": row["content"], "score": round(score, 4),
            })
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:max(1, min(limit, 20))]


def build_context(conn, query: str, kb_id: int | None, limit: int = 3, max_chars: int = 1200) -> str:
    chunks = search(conn, query, kb_id, limit)
    if not chunks:
        return ""
    parts = []
    used = 0
    for chunk in chunks:
        text = f"【{chunk['title']}】\n{chunk['content']}"
        if used + len(text) > max_chars:
            text = text[: max(0, max_chars - used)]
        if not text:
            break
        parts.append(text)
        used += len(text)
        if used >= max_chars:
            break
    return "\n\n".join(parts)


def stats(conn, owner_id: int | None = None) -> dict:
    where = " WHERE owner_id=?" if owner_id else ""
    args = (owner_id,) if owner_id else ()
    bases = conn.execute(f"SELECT COUNT(*) AS n FROM knowledge_bases{where}", args).fetchone()["n"]
    docs = conn.execute(
        "SELECT COUNT(*) AS n FROM knowledge_documents d "
        "JOIN knowledge_bases b ON b.id=d.kb_id" + (" WHERE b.owner_id=?" if owner_id else ""), args
    ).fetchone()["n"]
    chunks = conn.execute(
        "SELECT COUNT(*) AS n FROM knowledge_chunks c "
        "JOIN knowledge_bases b ON b.id=c.kb_id" + (" WHERE b.owner_id=?" if owner_id else ""), args
    ).fetchone()["n"]
    return {"bases": bases, "documents": docs, "chunks": chunks}
