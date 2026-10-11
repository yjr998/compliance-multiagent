"""通用场景入口：写出报告和轨迹。支持缺字段补填后续跑。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.rag.corpus import ROOT
from app.rag.index import HybridIndex
from app.rag.corpus import load_chunks
from app.workflow import run_scenario

SCENARIO_FILES = {
    "aliyun": "aliyun-cloud.json",
    "aliyun-cloud": "aliyun-cloud.json",
    "shein": "shein.json",
    "slack": "slack.json",
}

OUT_NAMES = {
    "aliyun-cloud.json": "aliyun",
    "shein.json": "shein",
    "slack.json": "slack",
}


def _parse_supplements(items: list[str] | None) -> dict:
    supplements: dict = {}
    for item in items or []:
        if "=" not in item:
            raise SystemExit(f"supplement 格式应为 key=value，收到：{item}")
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value.lower() in {"true", "false"}:
            supplements[key] = value.lower() == "true"
        elif value.startswith("[") and value.endswith("]"):
            supplements[key] = json.loads(value)
        else:
            supplements[key] = value
    return supplements


def _save(name: str, state: dict) -> None:
    reports = ROOT / "data" / "reports"
    traces = ROOT / "data" / "traces"
    reports.mkdir(parents=True, exist_ok=True)
    traces.mkdir(parents=True, exist_ok=True)
    (reports / f"{name}.md").write_text(state["report"], encoding="utf-8")
    trace = {
        "held": bool(state.get("held")),
        "questions": state.get("questions") or [],
        "trace": state["trace"],
        "risks": state["risks"],
        "evidence": [
            {"doc_id": item["doc_id"], "title": item["title"], "score": item["score"]}
            for item in state.get("evidence") or []
        ],
    }
    (traces / f"{name}.json").write_text(
        json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    supported = sum(item["status"] == "supported" for item in state["risks"])
    conflict = sum(item["status"] == "conflict" for item in state["risks"])
    missing = sum(item["status"] == "missing" for item in state["risks"])
    print(
        f"{name}: risks={len(state['risks'])} supported={supported} "
        f"conflict={conflict} missing={missing} held={bool(state.get('held'))}"
    )
    print(f"report={reports / f'{name}.md'}")
    print(f"trace={traces / f'{name}.json'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="跑合规预审场景")
    parser.add_argument(
        "scenario",
        nargs="?",
        default="aliyun",
        help="场景名：aliyun / shein / slack，或 scenarios 下的 json 文件名",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="依次跑 aliyun、shein、slack（共享检索索引）",
    )
    parser.add_argument(
        "--supplement",
        action="append",
        default=[],
        help="缺信息补填，可重复：--supplement company=SHEIN",
    )
    parser.add_argument(
        "--strip-company",
        action="store_true",
        help="演示缺信息岔路：去掉公司名后应 hold，不硬编风险",
    )
    parser.add_argument("--out", default="", help="输出文件名前缀，默认跟场景名")
    args = parser.parse_args()
    # 先演示清空，再用 --supplement 覆盖，便于「缺信息 → 补填续跑」
    supplements: dict = {}
    if args.strip_company:
        supplements["company"] = ""
    supplements.update(_parse_supplements(args.supplement))

    index = HybridIndex(load_chunks())

    if args.all:
        for key in ("aliyun", "shein", "slack"):
            filename = SCENARIO_FILES[key]
            path = ROOT / "data" / "scenarios" / filename
            state = run_scenario(path, supplements=None, index=index)
            _save(OUT_NAMES[filename], state)
        return

    key = args.scenario
    if key in SCENARIO_FILES:
        filename = SCENARIO_FILES[key]
        path = ROOT / "data" / "scenarios" / filename
        out_name = args.out or OUT_NAMES[filename]
    else:
        path = Path(key)
        if not path.is_file():
            path = ROOT / "data" / "scenarios" / key
        if not path.is_file():
            raise SystemExit(f"找不到场景：{args.scenario}")
        out_name = args.out or path.stem.replace("-cloud", "")

    # strip-company 演示时输出名加后缀，避免覆盖正常报告
    if args.strip_company and not args.out:
        out_name = f"{out_name}-missing"

    state = run_scenario(path, supplements=supplements or None, index=index)
    _save(out_name, state)


if __name__ == "__main__":
    main()
