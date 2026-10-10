"""检索评测，以及校验规则的对照。"""

from __future__ import annotations

import json
from pathlib import Path

from app.rag.corpus import ROOT, load_chunks
from app.rag.index import HybridIndex
from app.workflow import verify

CASES = ROOT / "data" / "eval" / "retrieval_cases.json"
OUT = ROOT / "data" / "eval" / "result.json"


def main() -> None:
    chunks = load_chunks()
    index = HybridIndex(chunks)
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    rows = []
    for case in cases:
        hits = index.search(case["query"], k=5)
        ok = any(case["expect"] in hit["text"] for hit in hits)
        rows.append(
            {
                "id": case["id"],
                "hit": ok,
                "top_titles": [hit["title"] for hit in hits[:3]],
            }
        )
    hit_count = sum(row["hit"] for row in rows)

    evidence = [
        {"doc_id": "e1", "text": "These Third Party Service Providers may be located in Singapore or outside of Singapore."}
    ]
    risks = [
        {
            "text": "may be located in Singapore or outside of Singapore",
            "level": "medium",
            "evidence_ids": ["e1"],
            "status": "assumption",
        },
        {
            "text": "TikTok stores every byte in Singapore under section 99.",
            "level": "high",
            "evidence_ids": ["e1"],
            "status": "assumption",
        },
        {
            "text": "personal data is transferred",
            "level": "medium",
            "evidence_ids": ["missing"],
            "status": "assumption",
        },
    ]
    checked = verify({"evidence": evidence, "risks": risks, "trace": []})["risks"]

    result = {
        "chunks": len(chunks),
        "retrieval_hit_at_5": f"{hit_count}/{len(rows)}",
        "retrieval": rows,
        "verifier": [
            {"text": item["text"][:80], "status": item["status"], "evidence_ids": item["evidence_ids"]}
            for item in checked
        ],
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
