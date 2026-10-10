"""跑阿里云场景，写出报告和轨迹。"""

from __future__ import annotations

import json
from pathlib import Path

from app.rag.corpus import ROOT
from app.workflow import run_scenario


def main() -> None:
    scenario = ROOT / "data" / "scenarios" / "aliyun-cloud.json"
    state = run_scenario(scenario)
    reports = ROOT / "data" / "reports"
    traces = ROOT / "data" / "traces"
    reports.mkdir(parents=True, exist_ok=True)
    traces.mkdir(parents=True, exist_ok=True)
    (reports / "aliyun.md").write_text(state["report"], encoding="utf-8")
    trace = {
        "questions": state["questions"],
        "trace": state["trace"],
        "risks": state["risks"],
        "evidence": [
            {"doc_id": item["doc_id"], "title": item["title"], "score": item["score"]}
            for item in state["evidence"]
        ],
    }
    (traces / "aliyun.json").write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
    supported = sum(item["status"] == "supported" for item in state["risks"])
    print(f"risks={len(state['risks'])} supported={supported}")
    print(f"report={reports / 'aliyun.md'}")


if __name__ == "__main__":
    main()
