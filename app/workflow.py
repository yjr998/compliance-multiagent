"""固定五步。检索和校验不调模型。"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from app.rag.corpus import ROOT, load_chunks
from app.rag.index import HybridIndex
from app.schemas import REPORT_SECTIONS

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen2.5:7b"


class GraphState(TypedDict, total=False):
    scenario: dict
    profile: dict
    evidence: list
    risks: list
    report: str
    trace: list
    questions: list
    index: Any


def _step(state: dict, node: str, note: str, hit_count: int = 0, started: float | None = None) -> list:
    elapsed = int((time.perf_counter() - started) * 1000) if started else 0
    return state["trace"] + [
        {"node": node, "elapsed_ms": elapsed, "note": note, "hit_count": hit_count}
    ]


def understand(state: dict) -> dict:
    started = time.perf_counter()
    scenario = state["scenario"]
    gaps = []
    if not scenario.get("company"):
        gaps.append("公司名称缺失")
    if not scenario.get("facts_from_source"):
        gaps.append("没有来自公开页面的业务事实")
    profile = {
        "region": "SG",
        "business_type": "cloud",
        "data_types": ["identity", "email", "phone", "photo_id"],
        "cross_border": True,
        "flow": "contracting data may be shared with Alibaba Cloud (Singapore); third parties may be outside Singapore",
        "service_mode": "cloud",
        "gaps": gaps,
    }
    return {
        "profile": profile,
        "questions": gaps,
        "trace": _step(state, "understand", f"gaps={len(gaps)}", started=started),
    }


def retrieve(state: dict) -> dict:
    started = time.perf_counter()
    scenario = state["scenario"]
    queries = [
        f"{scenario.get('company', '')} Singapore personal data third party outside Singapore",
        "向中华人民共和国境外提供个人信息 新加坡",
    ]
    hits = []
    seen: set[str] = set()
    for query in queries:
        for hit in state["index"].search(query, k=3):
            if hit["doc_id"] in seen:
                continue
            seen.add(hit["doc_id"])
            hits.append(hit)
    evidence = [
        {
            "doc_id": hit["doc_id"],
            "region": hit["region"],
            "doc_type": hit["doc_type"],
            "title": hit["title"],
            "text": hit["text"],
            "url": hit["url"],
            "score": hit["score"],
        }
        for hit in hits
    ]
    return {
        "evidence": evidence,
        "trace": _step(state, "retrieve", "BM25+TF-IDF", hit_count=len(evidence), started=started),
    }


def _ask_model(evidence: list[dict]) -> list[dict]:
    packed = "\n\n".join(
        f"[{item['doc_id']}] {item['text'][:500]}" for item in evidence
    )
    prompt = (
        "你是合规预审助手。只根据下面的证据写风险。"
        "每条 risk 的 text 必须是证据原文里的连续子串，不能改写。"
        "evidence_ids 只能填证据开头的 doc_id。"
        "输出 JSON：{\"risks\":[{\"text\":\"\",\"level\":\"medium\",\"evidence_ids\":[]}]}\n\n"
        + packed
    )
    body = json.dumps(
        {
            "model": MODEL,
            "stream": False,
            "format": "json",
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_URL, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = json.loads(response.read().decode("utf-8"))
    content = payload["message"]["content"]
    parsed = json.loads(content)
    risks = parsed.get("risks", [])
    cleaned = []
    for item in risks:
        if not isinstance(item, dict) or not item.get("text"):
            continue
        cleaned.append(
            {
                "text": str(item["text"]).strip(),
                "level": item.get("level") if item.get("level") in {"low", "medium", "high"} else "medium",
                "evidence_ids": [str(x) for x in item.get("evidence_ids") or []],
                "status": "assumption",
            }
        )
    return cleaned


def _extractive(evidence: list[dict]) -> list[dict]:
    risks = []
    for item in evidence[:3]:
        risks.append(
            {
                "text": item["text"][:400],
                "level": "medium",
                "evidence_ids": [item["doc_id"]],
                "status": "assumption",
            }
        )
    return risks


def analyze(state: dict) -> dict:
    started = time.perf_counter()
    note = "model"
    try:
        risks = _ask_model(state["evidence"])
    except Exception as exc:
        risks = []
        note = f"model_failed:{type(exc).__name__}"
    if not risks:
        risks = _extractive(state["evidence"])
        note = note + "+extractive_fallback" if note != "model" else "extractive_fallback"
    return {
        "risks": risks,
        "trace": _step(state, "analyze", note, hit_count=len(risks), started=started),
    }


def verify(state: dict) -> dict:
    started = time.perf_counter()
    by_id = {item["doc_id"]: item["text"] for item in state["evidence"]}
    checked = []
    supported = 0
    for risk in state["risks"]:
        ids = risk.get("evidence_ids") or []
        ok = bool(ids) and all(doc_id in by_id and risk["text"] in by_id[doc_id] for doc_id in ids)
        checked.append(
            {
                **risk,
                "evidence_ids": ids if ok else [],
                "status": "supported" if ok else "assumption",
            }
        )
        supported += int(ok)
    return {
        "risks": checked,
        "trace": _step(
            state,
            "verify",
            f"supported={supported}/{len(checked)}",
            hit_count=supported,
            started=started,
        ),
    }


def write_report(state: dict) -> dict:
    started = time.perf_counter()
    scenario = state["scenario"]
    supported = [item for item in state["risks"] if item["status"] == "supported"]
    assumptions = [item for item in state["risks"] if item["status"] != "supported"]
    lines = [
        "# 合规预审报告",
        "",
        "这不是法律意见。语料有限，结论需要人工复核。",
        "",
        "## 场景摘要",
        f"{scenario.get('company', '')} 国际站隐私政策中的公开表述。",
        "",
        "## 适用范围与材料来源",
        "检索命中的片段见附录。未检索到的法域不写成已覆盖。",
        "",
        "## 数据流与关键处理活动",
        state["profile"].get("flow", ""),
        "",
        "## 风险清单",
    ]
    if supported:
        for item in supported:
            lines.append(f"- （supported）{item['text']}")
    else:
        lines.append("- 没有能逐字对上原文的风险结论。")
    lines.extend(["", "## 信息缺口与冲突"])
    if assumptions:
        for item in assumptions:
            lines.append(f"- （assumption）模型给出的句子对不上证据原文：{item['text'][:180]}")
    else:
        lines.append("- 本轮没有被降级的句子。")
    lines.extend(
        [
            "",
            "## 建议与人工复核项",
            "请对照附录里的原文，确认是否还需要合同、评估或告知同意。",
            "",
            "## 附录：引用片段列表",
        ]
    )
    for item in state["evidence"]:
        lines.append(f"- {item['doc_id']} | {item['title']} | {item['url']}")
    report = "\n".join(lines) + "\n"
    return {
        "report": report,
        "trace": _step(state, "write_report", f"sections={len(REPORT_SECTIONS)}", started=started),
    }


def after_understand(state: dict) -> Literal["retrieve"]:
    return "retrieve"


def build_graph():
    builder = StateGraph(GraphState)
    for name, fn in [
        ("understand", understand),
        ("retrieve", retrieve),
        ("analyze", analyze),
        ("verify", verify),
        ("write_report", write_report),
    ]:
        builder.add_node(name, fn)
    builder.add_edge(START, "understand")
    builder.add_conditional_edges("understand", after_understand)
    builder.add_edge("retrieve", "analyze")
    builder.add_edge("analyze", "verify")
    builder.add_edge("verify", "write_report")
    builder.add_edge("write_report", END)
    return builder.compile()


def run_scenario(scenario_path: Path) -> dict:
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    index = HybridIndex(load_chunks())
    app = build_graph()
    return app.invoke(
        {
            "scenario": scenario,
            "profile": {},
            "evidence": [],
            "risks": [],
            "report": "",
            "trace": [],
            "questions": [],
            "index": index,
        }
    )
