"""≥30 评测：检索 Hit@5 + 校验 + 报告结构/缺信息/主题覆盖等行为用例。"""

from __future__ import annotations

import json
from pathlib import Path

from app.metrics import report_has_disclaimer, report_has_sections, untraceable_rate
from app.rag.corpus import ROOT, load_chunks
from app.rag.index import HybridIndex
from app.schemas import BusinessProfile, parse_evidence, parse_risks
from app.workflow import run_scenario_dict, verify

CASES = ROOT / "data" / "eval" / "retrieval_cases.json"
OUT = ROOT / "data" / "eval" / "result.json"
REPORT_DIR = ROOT / "data" / "reports"
SCENARIO_DIR = ROOT / "data" / "scenarios"

THEME_CHECKS = {
    "aliyun": [
        ("A1", ["Alibaba Cloud (Singapore) Private Limited", "signatory"]),
        ("A2", ["outside of Singapore", "Singapore or outside"]),
        ("A3", ["photo ID"]),
        ("A4", ["pipl", "pdpa", "境外", "shall not transfer"]),
    ],
    "shein": [
        ("S1", ["Roadget Business Pte"]),
        ("S2", ["United States, China and/or Singapore"]),
        ("S3_no_payment", []),  # special
        ("S4", ["pipl", "pdpa", "gdpr", "境外", "shall not transfer"]),
    ],
    "slack": [
        ("L1", ["stored outside this data region", "outside this data region"]),
        ("L2", ["Amazon Web Services", "Singapore"]),
        ("L3", ["Edge region", "Edge"]),
        ("L4_no_automotive", []),
        ("L5", ["GovSlack"]),
    ],
}


def _pass(rows: list[dict], case_id: str, ok: bool, detail: str = "") -> None:
    rows.append({"id": case_id, "pass": bool(ok), "detail": detail})


def _theme_ok(text: str, needles: list[str]) -> bool:
    low = text.lower()
    return any(n.lower() in low for n in needles)


def main() -> None:
    chunks = load_chunks()
    index = HybridIndex(chunks)
    rows: list[dict] = []

    # --- 15 检索 ---
    retrieval_cases = json.loads(CASES.read_text(encoding="utf-8"))
    hit_count = 0
    for case in retrieval_cases:
        hits = index.search(case["query"], k=5)
        ok = any(case["expect"] in hit["text"] for hit in hits)
        hit_count += int(ok)
        _pass(rows, f"retrieval:{case['id']}", ok, case["expect"][:60])

    # --- 校验器 ---
    evidence = [
        {
            "doc_id": "e1",
            "text": "These Third Party Service Providers may be located in Singapore or outside of Singapore.",
        },
        {
            "doc_id": "e2",
            "text": "An organisation shall not transfer any personal data to a country or territory outside Singapore except in accordance with requirements.",
        },
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
        {
            "text": "may be located in Singapore or outside of Singapore",
            "level": "high",
            "evidence_ids": ["e1", "e2"],
            "status": "assumption",
        },
        {
            "text": "shall not transfer any personal data to a country or territory outside Singapore",
            "level": "high",
            "evidence_ids": ["e2"],
            "status": "assumption",
        },
    ]
    checked = verify({"evidence": evidence, "risks": risks, "trace": [], "skip_verify": False})["risks"]
    statuses = [item["status"] for item in checked]
    _pass(rows, "verify:supported_or_conflict_clean", statuses[0] in {"supported", "conflict"})
    _pass(rows, "verify:fabricated_to_assumption", statuses[1] == "assumption")
    _pass(rows, "verify:missing_id_to_assumption", statuses[2] == "assumption")
    _pass(rows, "verify:same_risk_conflict", statuses[3] == "conflict")
    _pass(rows, "verify:cross_risk_conflict", statuses[4] == "conflict")
    rate = untraceable_rate(risks, evidence)
    _pass(rows, "metric:untraceable_pre_verify", rate["bad"] >= 2, str(rate))

    # --- Schema ---
    try:
        BusinessProfile(region="SG", business_type="cloud", gaps=["x"])
        parse_evidence(
            [
                {
                    "doc_id": "d1",
                    "text": "hello world evidence",
                    "region": "SG",
                    "doc_type": "privacy_policy",
                    "title": "t",
                    "url": "u",
                    "score": 1.0,
                }
            ]
        )
        parse_risks([{"text": "hello world evidence", "level": "medium", "evidence_ids": ["d1"]}])
        schema_ok = True
    except Exception as exc:  # noqa: BLE001
        schema_ok = False
        _pass(rows, "schema:roundtrip", False, type(exc).__name__)
    else:
        _pass(rows, "schema:roundtrip", schema_ok)
    try:
        parse_risks([{"text": "", "level": "nope"}])
        _pass(rows, "schema:reject_blank", False)
    except Exception:
        _pass(rows, "schema:reject_blank", True)

    # --- 缺信息 hold（不调模型）---
    shein = json.loads((SCENARIO_DIR / "shein.json").read_text(encoding="utf-8"))
    held = run_scenario_dict({**shein, "company": ""}, index=index)
    _pass(rows, "behavior:hold_missing_company", bool(held.get("held")))
    _pass(
        rows,
        "behavior:hold_no_supported_risks",
        not any(r.get("status") == "supported" for r in held.get("risks") or []),
    )
    _pass(rows, "behavior:hold_has_questions", bool(held.get("questions")))
    ok_sec, missing_sec = report_has_sections(held.get("report") or "")
    _pass(rows, "behavior:hold_report_sections", ok_sec, ",".join(missing_sec))
    _pass(rows, "behavior:hold_disclaimer", report_has_disclaimer(held.get("report") or ""))

    # --- 空证据 analyze 路径：构造 skip 到 verify 的最小状态 ---
    empty_state = verify(
        {
            "evidence": [],
            "risks": [
                {
                    "text": "检索未命中可用证据，本轮不编造风险结论",
                    "level": "medium",
                    "evidence_ids": [],
                    "status": "missing",
                }
            ],
            "trace": [],
        }
    )
    _pass(
        rows,
        "behavior:empty_evidence_stays_missing",
        empty_state["risks"][0]["status"] == "missing",
    )

    # --- 报告文件结构 / 禁区 / 主题 ---
    for name in ("aliyun", "shein", "slack"):
        path = REPORT_DIR / f"{name}.md"
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        ok_sec, missing_sec = report_has_sections(text)
        _pass(rows, f"report:{name}:sections", ok_sec and bool(text), ",".join(missing_sec))
        _pass(rows, f"report:{name}:disclaimer", report_has_disclaimer(text))

    shein_report = (REPORT_DIR / "shein.md").read_text(encoding="utf-8") if (REPORT_DIR / "shein.md").is_file() else ""
    _pass(
        rows,
        "report:shein:no_payment_invention",
        "credit card" not in shein_report.lower() and "支付卡" not in shein_report,
    )
    slack_report = (REPORT_DIR / "slack.md").read_text(encoding="utf-8") if (REPORT_DIR / "slack.md").is_file() else ""
    _pass(rows, "report:slack:no_automotive", "Automotive" not in slack_report)

    for scenario_name, checks in THEME_CHECKS.items():
        path = REPORT_DIR / f"{scenario_name}.md"
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        for theme_id, needles in checks:
            if theme_id.endswith("no_payment"):
                ok = "credit card" not in text.lower() and "支付卡" not in text
            elif theme_id.endswith("no_automotive"):
                ok = "Automotive" not in text
            else:
                ok = _theme_ok(text, needles)
            _pass(rows, f"theme:{scenario_name}:{theme_id}", ok, "|".join(needles[:2]))

    passed = sum(1 for r in rows if r["pass"])
    result = {
        "total": len(rows),
        "passed": passed,
        "score": f"{passed}/{len(rows)}",
        "retrieval_hit_at_5": f"{hit_count}/{len(retrieval_cases)}",
        "chunks": len(chunks),
        "cases": rows,
        "verifier_sample": [
            {"text": item["text"][:80], "status": item["status"], "evidence_ids": item["evidence_ids"]}
            for item in checked
        ],
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"score": result["score"], "retrieval_hit_at_5": result["retrieval_hit_at_5"]}, ensure_ascii=False))
    failed = [r for r in rows if not r["pass"]]
    if failed:
        print("FAILED:")
        for row in failed:
            print(f"  - {row['id']}: {row.get('detail')}")
    assert len(rows) >= 30, len(rows)
    assert hit_count == len(retrieval_cases), result["retrieval_hit_at_5"]
    # 允许主题覆盖尚未 100%（报告质量迭代），但核心行为必须过
    critical = [r for r in rows if not r["id"].startswith("theme:") and not r["pass"]]
    assert not critical, critical
    print("eval_ok")


if __name__ == "__main__":
    main()
