"""评测用：不可回溯引用比例、报告结构检查。"""

from __future__ import annotations

from app.schemas import REPORT_SECTIONS


def untraceable_rate(risks: list[dict], evidence: list[dict]) -> dict:
    """有 evidence_ids 的风险里，无法逐字对上原文的比例。"""
    by_id = {item["doc_id"]: item["text"] for item in evidence}
    claimed = [r for r in risks if r.get("evidence_ids")]
    if not claimed:
        return {"rate": 0.0, "bad": 0, "claimed": 0}
    bad = 0
    for risk in claimed:
        ids = risk.get("evidence_ids") or []
        ok = bool(ids) and all(
            doc_id in by_id and risk.get("text", "") in by_id[doc_id] for doc_id in ids
        )
        if not ok:
            bad += 1
    return {"rate": round(bad / len(claimed), 4), "bad": bad, "claimed": len(claimed)}


def report_has_sections(report: str) -> tuple[bool, list[str]]:
    missing = [name for name in REPORT_SECTIONS if f"## {name}" not in report]
    return (not missing, missing)


def report_has_disclaimer(report: str) -> bool:
    return "不是法律意见" in report and "人工复核" in report
