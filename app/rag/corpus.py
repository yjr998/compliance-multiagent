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
_SENTENCE_END = re.compile(r"[.!?。！？](?:\s+|$)")


def html_to_text(raw: str) -> str:
    entry = re.search(r'<div class="entry-content">([\s\S]*?)</div>', raw)
    if entry:
        raw = entry.group(1)
    text = _SCRIPT.sub(" ", raw)
    text = _STYLE.sub(" ", text)
    text = text.replace("&nbsp;", " ").replace("&#160;", " ")
    text = _TAG.sub(" ", text)
    return _SPACE.sub(" ", text).strip()


def _break_at(text: str, start: int, size: int) -> int:
    """尽量在句号附近结束；否则退到空白，避免拦腰截英文单词。"""
    end = min(len(text), start + size)
    if end >= len(text):
        return len(text)
    window = text[start:end]
    search_from = max(0, int(len(window) * 0.55))
    best = -1
    for match in _SENTENCE_END.finditer(window):
        if match.end() > search_from:
            best = match.end()
    if best > 0:
        return start + best
    space = window.rfind(" ")
    if space > int(len(window) * 0.4):
        return start + space + 1
    return end


def _chunks(text: str, size: int = 700, overlap: int = 120) -> list[str]:
    text = text.strip()
    if len(text) <= size:
        return [text] if len(text) >= 40 else []
    parts: list[str] = []
    start = 0
    while start < len(text):
        end = _break_at(text, start, size)
        piece = text[start:end].strip()
        if len(piece) >= 40:
            parts.append(piece)
        if end >= len(text):
            break
        next_start = max(0, end - overlap)
        while next_start < end and next_start < len(text) and not text[next_start].isspace():
            # 重叠起点也避开单词中间
            next_start += 1
        while next_start < len(text) and text[next_start].isspace():
            next_start += 1
        if next_start <= start:
            next_start = end
        start = next_start
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
