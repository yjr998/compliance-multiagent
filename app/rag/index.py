"""BM25 与 TF-IDF 混合检索，可按法域过滤。"""

from __future__ import annotations

import math
import re
from collections import Counter

from rank_bm25 import BM25Okapi

_WORD = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    parts = _WORD.findall(text.lower())
    tokens: list[str] = []
    cjk: list[str] = []

    def flush() -> None:
        if len(cjk) >= 2:
            tokens.extend(cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1))
        elif cjk:
            tokens.extend(cjk)
        cjk.clear()

    for part in parts:
        if len(part) == 1 and "\u4e00" <= part <= "\u9fff":
            cjk.append(part)
        else:
            flush()
            tokens.append(part)
    flush()
    return tokens


class HybridIndex:
    def __init__(self, chunks: list[dict]) -> None:
        self.chunks = chunks
        self._tokens = [tokenize(item["text"]) for item in chunks]
        self._bm25 = BM25Okapi(self._tokens)
        docs = [Counter(tokens) for tokens in self._tokens]
        df: Counter[str] = Counter()
        for doc in docs:
            df.update(doc.keys())
        n = max(len(docs), 1)
        self._idf = {term: math.log((n + 1) / (freq + 0.5)) for term, freq in df.items()}
        self._tfidf = []
        for doc in docs:
            vec = {term: (1 + math.log(count)) * self._idf.get(term, 0.0) for term, count in doc.items()}
            norm = math.sqrt(sum(value * value for value in vec.values())) or 1.0
            self._tfidf.append({term: value / norm for term, value in vec.items()})

    def search(self, query: str, k: int = 5, region: str | None = None) -> list[dict]:
        q_tokens = tokenize(query)
        bm25_scores = self._bm25.get_scores(q_tokens)
        q_tf = Counter(q_tokens)
        q_vec = {term: (1 + math.log(count)) * self._idf.get(term, 0.0) for term, count in q_tf.items()}
        q_norm = math.sqrt(sum(value * value for value in q_vec.values())) or 1.0
        q_vec = {term: value / q_norm for term, value in q_vec.items()}

        ranked: list[tuple[float, int]] = []
        for i, chunk in enumerate(self.chunks):
            if region and chunk.get("region") != region:
                continue
            dense = sum(q_vec.get(term, 0.0) * weight for term, weight in self._tfidf[i].items())
            score = 0.5 * float(bm25_scores[i]) + 0.5 * dense * 10
            ranked.append((score, i))
        ranked.sort(key=lambda item: item[0], reverse=True)
        hits = []
        for score, i in ranked[:k]:
            hit = dict(self.chunks[i])
            hit["score"] = round(score, 4)
            hits.append(hit)
        return hits
