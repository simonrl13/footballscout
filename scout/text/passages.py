"""Wikipedia passages for the agent's search_text tool: each demo player's English Wikipedia page as it stood on the
demo date (the latest fetched revision if that one is missing), split into paragraphs that keep their section name,
and indexed with Postgres full-text search. Every passage keeps its revision (doc_id) so answers can cite it exactly.

Usage: uv run --env-file .env python -m scout.text.passages     (loader role; rebuilds the table)
"""
import re

from scout.text import store
from scout.text.extract_wiki import is_heading

DDL = """
CREATE TABLE IF NOT EXISTS text_passages (
    doc_id     text NOT NULL REFERENCES text_documents (doc_id),
    passage_no integer NOT NULL,
    player_id  integer NOT NULL,
    section    text,
    body       text NOT NULL,
    tsv        tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(section, '') || ' ' || body)) STORED,
    PRIMARY KEY (doc_id, passage_no)
);
CREATE INDEX IF NOT EXISTS text_passages_tsv ON text_passages USING gin (tsv);
CREATE INDEX IF NOT EXISTS text_passages_player ON text_passages (player_id);
"""
MAX_CHARS = 1200
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


def split(body: str) -> list[tuple[str | None, str]]:
    """(section, passage) pairs: paragraphs, long ones cut at sentence ends into <= MAX_CHARS pieces. Heading-like
    lines name the section and stay in the text (a short one-sentence paragraph can look like a heading)."""
    out, section = [], None
    for para in re.split(r"\n\s*\n", body):
        lines = [ln.strip() for ln in para.split("\n") if ln.strip()]
        for ln in lines:
            if is_heading(ln):
                section = ln.rstrip(".")
        text = " ".join(lines)
        if len(text) < 40:  # headings and stubs alone are not passages
            continue
        piece = ""
        for s in _SENT.split(text):
            if piece and len(piece) + len(s) + 1 > MAX_CHARS:
                out.append((section, piece))
                piece = ""
            piece = f"{piece} {s}".strip()
        if piece:
            out.append((section, piece[:MAX_CHARS]))
    return out


def main() -> None:
    with store.connect() as conn:
        conn.execute(DDL)
        docs = conn.execute("""
            SELECT DISTINCT ON (r.player_id) r.player_id, r.doc_id, d.body
            FROM wiki_snapshot_revisions r JOIN text_documents d USING (doc_id)
            WHERE r.doc_id IS NOT NULL AND r.player_id IN (SELECT player_id FROM demo_players)
              AND r.as_of <= (SELECT max(as_of) FROM demo_players)
            ORDER BY r.player_id, r.as_of DESC""").fetchall()
        conn.execute("TRUNCATE text_passages")
        rows = [(doc_id, i, pid, sec, text) for pid, doc_id, body in docs for i, (sec, text) in enumerate(split(body or ""))]
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO text_passages (doc_id, passage_no, player_id, section, body) VALUES (%s, %s, %s, %s, %s)",
                            rows)
        conn.commit()
    print(f"text_passages: {len(rows):,} passages from {len(docs):,} players' pages")


if __name__ == "__main__":
    main()
