"""Company knowledge: ingestion (website, PDFs, OCR), versioning, hybrid retrieval, grounding checks."""
from __future__ import annotations

import hashlib
import logging
import re
import urllib.robotparser
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urljoin, urldefrag, urlparse

import numpy as np

from . import db
from .config import get_settings
from .language import extract
from .taxonomy import crops

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- embeddings
class Embedder(Protocol):
    def embed(self, texts: list[str]) -> np.ndarray: ...


class BGEM3:
    def __init__(self, name: str):
        from sentence_transformers import SentenceTransformer

        self.m = SentenceTransformer(name)

    def embed(self, texts):
        return np.asarray(self.m.encode(texts, normalize_embeddings=True, batch_size=16), dtype=np.float32)


class HashEmbedder:
    """Character n-gram hashing. DEV/TEST ONLY: no cross-lingual meaning. Use BGE-M3 in real runs."""

    def __init__(self, dim: int):
        self.dim = dim

    def embed(self, texts):
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            t = f"  {t.lower()}  "
            for j in range(len(t) - 2):
                h = int(hashlib.md5(t[j:j + 3].encode()).hexdigest()[:8], 16)
                out[i, h % self.dim] += 1.0
            n = np.linalg.norm(out[i])
            if n:
                out[i] /= n
        return out


_emb: Embedder | None = None


def get_embedder() -> Embedder:
    global _emb
    if _emb is None:
        s = get_settings()
        if s.embedding_provider == "bge-m3":
            try:
                _emb = BGEM3(s.embedding_model)
            except Exception as e:
                log.warning("BGE-M3 unavailable (%s) -> hashing embedder (lexical quality only)", e)
                _emb = HashEmbedder(s.embedding_dim)
        else:
            _emb = HashEmbedder(s.embedding_dim)
    return _emb


_reranker = None
_reranker_failed = False


def get_reranker():
    global _reranker, _reranker_failed
    s = get_settings()
    if not s.reranker_model or _reranker_failed:
        return None
    if _reranker is None:
        try:
            from sentence_transformers import CrossEncoder

            _reranker = CrossEncoder(s.reranker_model)
        except Exception as e:
            log.warning("reranker unavailable: %s", e)
            _reranker_failed = True
    return _reranker


# ---------------------------------------------------------------- chunking + tagging
def clean(text: str) -> str:
    text = text.replace(" ", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk(text: str, size: int = 1200, overlap: int = 200) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out, cur = [], ""
    for p in paras:
        if len(cur) + len(p) + 2 <= size:
            cur = f"{cur}\n\n{p}" if cur else p
            continue
        if cur:
            out.append(cur)
        while len(p) > size:  # very long paragraph
            out.append(p[:size])
            p = p[size - overlap:]
        cur = (out[-1][-overlap:] + "\n\n" + p) if out and overlap else p
    if cur:
        out.append(cur)
    return out


def tag(text: str) -> tuple[list[str], list[str]]:
    e = extract(text)
    found_problems = []
    low = text.lower()
    for c, meta in crops().items():
        for key, p in meta["problems"].items():
            if p["en"].lower().split(" (")[0] in low or p["ta"] in text:
                found_problems.append(key)
    return sorted(set(e.crops)), sorted(set(found_problems))


def detect_lang(text: str) -> str:
    tamil = len(re.findall(r"[஀-௿]", text))
    return "ta" if tamil > 0.2 * max(1, sum(c.isalpha() for c in text)) else "en"


# ---------------------------------------------------------------- storing with versions
def store_document(url_or_path: str, title: str, source_type: str, pages: list[tuple[int | None, str]]) -> str:
    """pages: [(page_number_or_None, text)]. Returns 'unchanged' | 'new' | 'updated'."""
    full = "\n".join(t for _, t in pages)
    sha = hashlib.sha256(full.encode()).hexdigest()
    prev = db.fetchone("SELECT id, sha256, version FROM documents WHERE url_or_path=%s AND status='active' "
                       "ORDER BY version DESC LIMIT 1", (url_or_path,))
    if prev and prev["sha256"] == sha:
        return "unchanged"
    version = (prev["version"] + 1) if prev else 1
    if prev:
        db.execute("UPDATE documents SET status='superseded' WHERE id=%s", (prev["id"],))
        db.execute("UPDATE chunks SET status='superseded' WHERE document_id=%s", (prev["id"],))
    doc = db.fetchone(
        "INSERT INTO documents (source_type, title, url_or_path, language, sha256, version) "
        "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
        (source_type, title, url_or_path, detect_lang(full), sha, version))
    rows = []
    for page, text in pages:
        for c in chunk(clean(text)):
            if len(c) < 40:
                continue
            cr, pr = tag(c)
            rows.append((page, c, cr, pr))
    if rows:
        vecs = get_embedder().embed([r[1] for r in rows])
        with db.conn() as cx:
            for (page, c, cr, pr), v in zip(rows, vecs):
                cx.execute(
                    "INSERT INTO chunks (document_id, page, content, language, crops, problems, embedding) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s)", (doc["id"], page, c, detect_lang(c), cr, pr, v))
    log.info("stored %s v%s (%d chunks)", url_or_path, version, len(rows))
    return "updated" if prev else "new"


# ---------------------------------------------------------------- sources
def pdf_pages(path: str) -> list[tuple[int, str]]:
    import pymupdf as fitz

    pages = []
    with fitz.open(path) as d:
        for i, page in enumerate(d, start=1):
            text = page.get_text("text")
            try:  # keep dosage tables as rows instead of flattened words
                for tb in page.find_tables().tables:
                    rows = tb.extract()
                    text += "\n\n" + "\n".join(" | ".join((c or "").strip() for c in r) for r in rows)
            except Exception:
                pass
            if len(text.strip()) < 80:  # scanned page or image brochure -> OCR (Tamil + English)
                ocr_txt = ocr_page(page)
                text = (text + "\n" + ocr_txt).strip()
            pages.append((i, text))
    return pages


def ocr_page(page) -> str:
    try:
        import io

        import pytesseract
        from PIL import Image

        pix = page.get_pixmap(dpi=200)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        langs = "tam+eng" if "tam" in pytesseract.get_languages(config="") else "eng"
        return pytesseract.image_to_string(img, lang=langs)
    except Exception as e:
        log.warning("OCR failed: %s", e)
        return ""


def ingest_pdf(path: str, source_type: str = "brochure") -> str:
    return store_document(Path(path).name, Path(path).stem, source_type, pdf_pages(path))


def html_to_text(html: str) -> tuple[str, str]:
    import trafilatura

    text = trafilatura.extract(html, include_tables=True, favor_recall=True) or ""
    m = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    return (m.group(1).strip() if m else ""), text


def ingest_html(url: str, html: str, source_type: str = "website") -> str:
    title, text = html_to_text(html)
    if len(text) < 40:
        return "empty"
    return store_document(url, title or url, source_type, [(None, text)])


def crawl(start_url: str, max_pages: int = 200) -> dict:
    """Same-domain crawl that respects robots.txt. PDFs found on the site are ingested as brochures."""
    import httpx

    dom = urlparse(start_url).netloc
    rp = urllib.robotparser.RobotFileParser(urljoin(start_url, "/robots.txt"))
    try:
        rp.read()
    except Exception:
        rp = None
    seen, q, stats = set(), deque([start_url]), {"new": 0, "updated": 0, "unchanged": 0, "empty": 0, "errors": 0}
    with httpx.Client(follow_redirects=True, timeout=30, headers={"User-Agent": "VishakanAgriBot/1.0"}) as c:
        while q and len(seen) < max_pages:
            url = urldefrag(q.popleft())[0]
            path_low = urlparse(url).path.lower()
            if any(path_low.endswith(ext) for ext in (".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2", ".webp")):
                continue
            if "/wp-json" in url or "/wp-admin" in url:
                continue
            if url in seen or urlparse(url).netloc != dom or (rp and not rp.can_fetch("*", url)):
                continue
            seen.add(url)
            try:
                r = c.get(url)
                ctype = r.headers.get("content-type", "")
                if "pdf" in ctype or url.lower().endswith(".pdf"):
                    tmp = Path(get_settings().media_dir) / "crawl" / Path(urlparse(url).path).name
                    tmp.parent.mkdir(parents=True, exist_ok=True)
                    tmp.write_bytes(r.content)
                    res = store_document(url, tmp.stem, "brochure", pdf_pages(str(tmp)))
                elif "html" in ctype:
                    res = ingest_html(url, r.text)
                    for href in re.findall(r'href=["\']([^"\'#]+)', r.text):
                        q.append(urljoin(url, href))
                else:
                    continue
                stats[res] = stats.get(res, 0) + 1
            except Exception as e:
                log.warning("crawl error %s: %s", url, e)
                stats["errors"] += 1
    return stats


# ---------------------------------------------------------------- retrieval
@dataclass
class Hit:
    id: str
    content: str
    title: str
    ref: str
    score: float


def _tsquery(text: str) -> str:
    toks = [t for t in re.findall(r"[\w஀-௿]+", text.lower()) if len(t) > 2][:24]
    return " | ".join(dict.fromkeys(toks)) or "zzzz"


def retrieve(query: str, crop: str | None = None, k: int | None = None) -> list[Hit]:
    s = get_settings()
    k = k or s.top_k
    # A chunk tagged only with OTHER crops is excluded; untagged (general) chunks are allowed.
    crop_filter = "AND (cardinality(c.crops) = 0 OR %(crop)s = ANY(c.crops))" if crop else ""
    base = ("SELECT c.id::text, c.content, d.title, d.url_or_path, c.page FROM chunks c "
            "JOIN documents d ON d.id = c.document_id WHERE c.status='active' AND d.status='active' " + crop_filter)
    qv = get_embedder().embed([query])[0]
    dense = db.fetchall(base + " ORDER BY c.embedding <=> %(v)s LIMIT 40", {"v": qv, "crop": crop})
    lex = db.fetchall(base.replace("SELECT c.id::text", "SELECT ts_rank(c.tsv, to_tsquery('simple', %(q)s)) AS r, c.id::text")
                      + " AND c.tsv @@ to_tsquery('simple', %(q)s) ORDER BY r DESC LIMIT 40",
                      {"q": _tsquery(query), "crop": crop})
    rrf: dict[str, float] = {}
    rows: dict[str, dict] = {}
    for lst, w in ((dense, 1.0), (lex, 1.0)):
        for rank, r in enumerate(lst):
            rrf[r["id"]] = rrf.get(r["id"], 0) + w / (60 + rank)
            rows[r["id"]] = r
    # Dense-only matches with low similarity are noise; require lexical support or real similarity.
    lex_ids = {r["id"] for r in lex}
    ranked = sorted(rrf, key=lambda i: -rrf[i])[:20]
    hits = []
    for i in ranked:
        r = rows[i]
        ref = r["url_or_path"] + (f" p.{r['page']}" if r["page"] else "")
        hits.append(Hit(i, r["content"], r["title"] or r["url_or_path"], ref, rrf[i] if i in lex_ids else rrf[i] / 2))
    rr = get_reranker()
    if rr and hits:
        scores = rr.predict([(query, h.content) for h in hits])
        for h, sc in zip(hits, scores):
            h.score = float(sc)
        hits = [h for h in sorted(hits, key=lambda h: -h.score) if h.score >= s.rerank_min_score]
    else:
        hits = [h for h in hits if h.score >= s.retrieval_min_score]
    return hits[:k]


# ---------------------------------------------------------------- grounding validator
NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")


def unsupported_numbers(answer: str, contexts: list[str]) -> list[str]:
    answer = re.sub(r"\[\d+(?:,\s*\d+)*\]", " ", answer)  # citation markers are not facts
    ctx = " ".join(contexts)
    ctx_nums = {n.replace(",", ".") for n in NUM_RE.findall(ctx)}
    return [n for n in NUM_RE.findall(answer) if n.replace(",", ".") not in ctx_nums]
