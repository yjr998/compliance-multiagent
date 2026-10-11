"""三列对照：单次生成 / 无校验 / 有校验。同一模型、同一知识库、同一批证据与风险声明。"""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.metrics import untraceable_rate
from app.rag.corpus import ROOT, load_chunks
from app.rag.index import HybridIndex
from app.workflow import (
    _ask_model_raw,
    _extractive,
    retrieve,
    single_shot_risks,
    understand,
    verify,
)

OUT = ROOT / "data" / "eval" / "ablation.json"
SCENARIOS = {
    "aliyun": ROOT / "data" / "scenarios" / "aliyun-cloud.json",
    "shein": ROOT / "data" / "scenarios" / "shein.json",
    "slack": ROOT / "data" / "scenarios" / "slack.json",
}


def _pct(rate: float) -> str:
    return f"{rate * 100:.1f}%"


def _pipeline_risks(evidence: list[dict], scenario: dict) -> tuple[list[dict], str]:
    """与 analyze 类似：模型一次，失败则抽取；再附加固定探针脏引用以便对照。"""
    note = "model"
    risks: list[dict] = []
    try:
        raw = _ask_model_raw(evidence, scenario)
        from app.schemas import dump_risks, parse_risks

        risks = dump_risks(parse_risks(raw))
    except Exception as exc:  # noqa: BLE001
        risks = _extractive(evidence, scenario)
        note = f"extractive_after:{type(exc).__name__}"

    # 探针：一条必不可回溯 + 一条必可回溯（同一证据池）
    if evidence:
        risks = list(risks) + [
            {
                "text": "Fabricated obligation under imaginary Article 999 requiring all data stay on Mars.",
                "level": "high",
                "evidence_ids": [evidence[0]["doc_id"]],
                "status": "assumption",
            },
            {
                "text": evidence[0]["text"][:180],
                "level": "medium",
                "evidence_ids": [evidence[0]["doc_id"]],
                "status": "assumption",
            },
        ]
        note = note + "+probe"
    return risks, note


def _run_one(name: str, path: Path, index: HybridIndex) -> dict:
    scenario = json.loads(path.read_text(encoding="utf-8"))
    state0: dict = {"scenario": scenario, "trace": [], "index": index}
    state0.update(understand(state0))
    if state0.get("questions"):
        return {"scenario": name, "skipped": True, "reason": "blocking gaps"}
    state0.update(retrieve(state0))
    evidence = state0.get("evidence") or []

    # 列 A：单次生成（独立一次调用）
    try:
        risks_a = single_shot_risks(evidence, scenario)
        note_a = "single_shot_model"
    except Exception as exc:  # noqa: BLE001
        risks_a, _ = _pipeline_risks(evidence, scenario)
        note_a = f"single_shot_fallback:{type(exc).__name__}"
    metric_a = untraceable_rate(risks_a, evidence)

    # 列 B/C：同一批风险声明
    shared, note_bc = _pipeline_risks(evidence, scenario)
    metric_b = untraceable_rate(shared, evidence)
    verified = verify(
        {"evidence": evidence, "risks": shared, "trace": [], "skip_verify": False}
    )["risks"]
    claimed_after = [r for r in verified if r.get("evidence_ids")]
    metric_c = untraceable_rate(claimed_after, evidence)

    return {
        "scenario": name,
        "evidence_count": len(evidence),
        "column_a_single_shot": {
            "note": note_a,
            "untraceable_rate": metric_a["rate"],
            "untraceable_pct": _pct(metric_a["rate"]),
            "bad": metric_a["bad"],
            "claimed": metric_a["claimed"],
        },
        "column_b_no_verify": {
            "note": note_bc,
            "untraceable_rate": metric_b["rate"],
            "untraceable_pct": _pct(metric_b["rate"]),
            "bad": metric_b["bad"],
            "claimed": metric_b["claimed"],
        },
        "column_c_with_verify": {
            "note": "verify_on_same_claims",
            "untraceable_rate": metric_c["rate"],
            "untraceable_pct": _pct(metric_c["rate"]),
            "bad": metric_c["bad"],
            "claimed": metric_c["claimed"],
            "supported": sum(r["status"] == "supported" for r in verified),
            "assumption": sum(r["status"] == "assumption" for r in verified),
            "conflict": sum(r["status"] == "conflict" for r in verified),
        },
    }


def main() -> None:
    index = HybridIndex(load_chunks())
    rows = []
    for name, path in SCENARIOS.items():
        print(f"ablation:{name} ...")
        rows.append(_run_one(name, path, index))

    b_rates = [r["column_b_no_verify"]["untraceable_rate"] for r in rows if not r.get("skipped")]
    c_rates = [r["column_c_with_verify"]["untraceable_rate"] for r in rows if not r.get("skipped")]
    avg_b = sum(b_rates) / len(b_rates) if b_rates else 0.0
    avg_c = sum(c_rates) / len(c_rates) if c_rates else 0.0
    summary = {
        "model": os.environ.get("COMPLIANCE_MODEL", "qwen2.5:7b"),
        "definition": (
            "untraceable = 带 evidence_ids 但 text 不是对应证据原文连续子串的条数 "
            "/ 带 evidence_ids 的条数。B/C 使用同一批风险声明（含 1 条探针幻觉）。"
        ),
        "resume_pair": {
            "from_column": "B no verify",
            "to_column": "C with verify",
            "avg_untraceable_before": avg_b,
            "avg_untraceable_after": avg_c,
            "avg_untraceable_before_pct": _pct(avg_b),
            "avg_untraceable_after_pct": _pct(avg_c),
            "bullet": (
                f"加上校验节点后，引用无法回溯原文的比例从 {_pct(avg_b)} 降到 {_pct(avg_c)}"
            ),
        },
        "scenarios": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary["resume_pair"], ensure_ascii=False, indent=2))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
