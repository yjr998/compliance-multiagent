"""把语料文件切成带来源的片段。目录页不进入检索。"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "data" / "corpus"
CATALOG = CORPUS / "catalog.json"

_TAG = re.compile(r"<[^>]+>")
_SCRIPT = re.compile(r"<script[\s\S]*?</script>", re.I)
_STYLE = re.compile(r"<style[\s\S]*?</style>", re.I)
_SPACE = re.compile(r"\s+")


def html_to_text(raw: str) -> str:
    entry = re.search(r'<div class="entry-content">([\s\S]*?)</div>', raw)
    if entry:
        raw = entry.group(1)
    text = _SCRIPT.sub(" ", raw)
    text = _STYLE.sub(" ", text)
    text = text.replace("&nbsp;", " ").replace("&#160;", " ")
    text = _TAG.sub(" ", text)
    return _SPACE.sub(" ", text).strip()


def _chunks(text: str, size: int = 700, overlap: int = 120) -> list[str]:
    text = text.strip()
    if len(text) <= size:
        return [text] if len(text) >= 40 else []
    parts: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        piece = text[start:end].strip()
        if len(piece) >= 40:
            parts.append(piece)
        if end == len(text):
            break
        start = end - overlap
    return parts


def _catalog() -> list[dict]:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def _read_file(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        doc = pymupdf.open(path)
        return _SPACE.sub(" ", "\n".join(page.get_text() for page in doc)).strip()
    return html_to_text(path.read_text(encoding="utf-8", errors="ignore"))


def load_chunks() -> list[dict]:
    chunks: list[dict] = []
    for item in _catalog():
        if item.get("status") == "contents_only":
            continue
        rel = item["file"]
        if rel.startswith("gdpr/"):
            folder = CORPUS / "gdpr"
            for path in sorted(folder.glob("art-*.html")):
                number = path.stem.split("-")[1]
                text = _read_file(path)
                for i, piece in enumerate(_chunks(text)):
                    chunks.append(
                        {
                            "doc_id": f"gdpr-art-{number}-{i}",
                            "parent_id": item["doc_id"],
                            "region": "EU",
                            "doc_type": "statute_mirror",
                            "title": f"GDPR Article {int(number)}",
                            "url": f"https://gdpr-info.eu/art-{int(number)}-gdpr/",
                            "text": piece,
                        }
                    )
            continue
        path = CORPUS / rel
        if not path.exists():
            continue
        text = _read_file(path)
        for i, piece in enumerate(_chunks(text)):
            chunks.append(
                {
                    "doc_id": f"{item['doc_id']}-{i}",
                    "parent_id": item["doc_id"],
                    "region": item.get("region", ""),
                    "doc_type": item.get("doc_type", ""),
                    "title": item.get("title", path.name),
                    "url": item.get("url", ""),
                    "text": piece,
                }
            )
    return chunks
