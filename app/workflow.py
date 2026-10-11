"""固定五步。检索和校验不调模型。步骤间用 Pydantic Schema 交接。"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from app.rag.corpus import load_chunks
from app.rag.index import HybridIndex
from app.schemas import (
    REPORT_SECTIONS,
    BusinessProfile,
    dump_evidence,
    dump_risks,
    dump_trace_step,
    parse_evidence,
    parse_risks,
)

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MODEL = os.environ.get("COMPLIANCE_MODEL", "qwen2.5:7b")
OLLAMA_TIMEOUT = int(os.environ.get("COMPLIANCE_TIMEOUT", "180"))

_ALLOWS_CROSS = re.compile(
    r"(outside (of )?(singapore|the country|prc|china)|"
    r"transferred? (outside|abroad|to (the )?(united states|china|a (third )?country))|"
    r"may be (processed or )?transferred|"
    r"located in singapore or outside|"
    r"stored outside this data region|"
    r"向.{0,8}境外提供)",
    re.I,
)
_RESTRICTS_CROSS = re.compile(
    r"(shall not transfer|will not transfer|must not transfer|"
    r"only (within|in) singapore|stored only in singapore|"
    r"不得向境外|禁止跨境)",
    re.I,
)


class GraphState(TypedDict, total=False):
    scenario: dict
    profile: dict
    evidence: list
    risks: list
    report: str
    trace: list
    questions: list
    index: Any
    held: bool
    skip_verify: bool


def _step(state: dict, node: str, note: str, hit_count: int = 0, started: float | None = None) -> list:
    elapsed = int((time.perf_counter() - started) * 1000) if started else 0
    return list(state.get("trace") or []) + [
        dump_trace_step(node=node, note=note, hit_count=hit_count, elapsed_ms=elapsed)
    ]


def _blocking_gaps(scenario: dict) -> list[str]:
    gaps: list[str] = []
    if not str(scenario.get("company") or "").strip():
        gaps.append("公司名称缺失")
    if not scenario.get("facts_from_source"):
        gaps.append("没有来自公开页面的业务事实")
    if not str(scenario.get("region") or "").strip():
        gaps.append("目标法域缺失")
    if not str(scenario.get("business_type") or "").strip():
        gaps.append("业务类型缺失")
    return gaps


def _flow_from_scenario(scenario: dict) -> str:
    facts = scenario.get("facts_from_source") or []
    if facts:
        return " | ".join(str(item).strip() for item in facts if str(item).strip())
    return ""


def understand(state: dict) -> dict:
    started = time.perf_counter()
    scenario = state["scenario"]
    gaps = _blocking_gaps(scenario)
    soft: list[str] = []
    if scenario.get("cross_border") is None and not any(
        "transfer" in str(f).lower() or "境外" in str(f) for f in (scenario.get("facts_from_source") or [])
    ):
        soft.append("未标明是否跨境；报告中跨境结论将更谨慎")
    profile = BusinessProfile(
        region=str(scenario.get("region") or "").strip(),
        business_type=str(scenario.get("business_type") or "").strip(),
        data_types=list(scenario.get("data_types") or []),
        cross_border=scenario.get("cross_border"),
        flow=_flow_from_scenario(scenario),
        service_mode=str(scenario.get("service_mode") or "").strip(),
        gaps=gaps + soft,
    )
    return {
        "profile": profile.model_dump(),
        "questions": gaps,
        "held": bool(gaps),
        "trace": _step(state, "understand", f"gaps={len(gaps)} soft={len(soft)}", started=started),
    }


def hold(state: dict) -> dict:
    started = time.perf_counter()
    questions = list(state.get("questions") or [])
    scenario = state["scenario"]
    company = str(scenario.get("company") or "").strip() or "（未填）"
    risks = dump_risks(
        parse_risks(
            [
                {
                    "text": q,
                    "level": "medium",
                    "evidence_ids": [],
                    "status": "missing",
                }
                for q in questions
            ]
            or [
                {
                    "text": "关键字段缺失",
                    "level": "medium",
                    "evidence_ids": [],
                    "status": "missing",
                }
            ]
        )
    )
    lines = [
        "# 合规预审报告",
        "",
        "这不是法律意见。语料有限，结论需要人工复核。",
        "",
        "## 场景摘要",
        f"{company}：关键字段不足，本轮未继续检索与风险分析。",
        "",
        "## 适用范围与材料来源",
        "因信息缺口已中止，本轮未检索语料。",
        "",
        "## 数据流与关键处理活动",
        state.get("profile", {}).get("flow") or "未提供可用事实，无法描述数据流。",
        "",
        "## 风险清单",
        "- 本轮未生成风险结论（避免在缺字段时硬编）。",
        "",
        "## 信息缺口与冲突",
    ]
    for q in questions:
        lines.append(f"- （missing）{q}")
    lines.extend(
        [
            "",
            "## 建议与人工复核项",
            "请补全上述缺口后重新运行（可用脚本的 --supplement 或传入 supplements）。",
            "",
            "## 附录：引用片段列表",
            "- （无）",
        ]
    )
    return {
        "risks": risks,
        "evidence": [],
        "report": "\n".join(lines) + "\n",
        "held": True,
        "trace": _step(state, "hold", f"stopped questions={len(questions)}", hit_count=0, started=started),
    }


_VENDOR_DOCS = {
    "alibaba cloud": ("aliyun-intl-privacy", "alibaba cloud"),
    "shein": ("shein-privacy", "shein", "roadget"),
    "slack": ("slack-subprocessors", "slack"),
}


def _other_vendor_hit(hit: dict, company: str) -> bool:
    doc_type = str(hit.get("doc_type") or "")
    if doc_type in {"statute", "statute_mirror", "statute_transcription"}:
        return False
    blob = f"{hit.get('doc_id', '')} {hit.get('title', '')} {hit.get('parent_id', '')}".lower()
    company_l = company.lower()
    for vendor, markers in _VENDOR_DOCS.items():
        if vendor in company_l or company_l in vendor:
            continue
        if any(marker in blob for marker in markers):
            return True
    return False


def _hit_matches_company_or_facts(hit: dict, company: str, facts: list[str]) -> bool:
    text = hit.get("text") or ""
    if company and company.lower() in text.lower():
        return True
    return any(fact[:80] in text for fact in facts if len(fact) >= 20)


def retrieve(state: dict) -> dict:
    started = time.perf_counter()
    scenario = state["scenario"]
    company = str(scenario.get("company") or "").strip()
    region = str(scenario.get("region") or "").strip()
    facts = [str(f) for f in (scenario.get("facts_from_source") or []) if str(f).strip()]
    queries: list[str] = []
    for fact in facts[:2]:
        queries.append(fact[:200])
    if company:
        queries.append(f"{company} personal data transfer {region}".strip())
        queries.append(f"{company} Singapore")
    if region == "SG" or any("Singapore" in f for f in facts):
        queries.append("transfer personal data outside Singapore comparable protection")
    queries.append("向中华人民共和国境外提供个人信息")
    seen_q: set[str] = set()
    ordered: list[str] = []
    for q in queries:
        q = q.strip()
        if q and q not in seen_q:
            seen_q.add(q)
            ordered.append(q)

    hits = []
    seen: set[str] = set()
    for query in ordered:
        for hit in state["index"].search(query, k=4):
            if hit["doc_id"] in seen:
                continue
            if company and _other_vendor_hit(hit, company):
                continue
            seen.add(hit["doc_id"])
            hits.append(hit)

    hits.sort(
        key=lambda h: (
            0 if _hit_matches_company_or_facts(h, company, facts) else 1,
            -float(h.get("score") or 0),
        )
    )
    try:
        evidence_models = parse_evidence(
            [
                {
                    "doc_id": hit["doc_id"],
                    "region": hit.get("region", ""),
                    "doc_type": hit.get("doc_type", ""),
                    "title": hit.get("title", ""),
                    "text": hit["text"],
                    "url": hit.get("url", ""),
                    "score": float(hit.get("score") or 0),
                }
                for hit in hits[:12]
            ]
        )
        evidence = dump_evidence(evidence_models)
        note = "BM25+TF-IDF"
    except (ValidationError, ValueError) as exc:
        evidence = []
        note = f"schema_failed:{type(exc).__name__}"
    return {
        "evidence": evidence,
        "trace": _step(state, "retrieve", note, hit_count=len(evidence), started=started),
    }


def _ask_model_raw(evidence: list[dict], scenario: dict) -> Any:
    packed = "\n\n".join(f"[{item['doc_id']}] {item['text'][:500]}" for item in evidence)
    company = scenario.get("company", "")
    prompt = (
        f"你是合规预审助手。场景公司：{company}。"
        "只根据下面的证据写风险。"
        "每条 risk 的 text 必须是证据原文里的连续子串，不能改写。"
        "evidence_ids 只能填证据开头的 doc_id。"
        "不要使用证据以外的公司名或事实。"
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
    with urllib.request.urlopen(request, timeout=OLLAMA_TIMEOUT) as response:
        payload = json.loads(response.read().decode("utf-8"))
    content = payload["message"]["content"]
    return json.loads(content).get("risks", [])


def single_shot_risks(evidence: list[dict], scenario: dict) -> list[dict]:
    """三列对照第 1 列：单次生成风险清单（不做流水线校验）。"""
    packed = "\n\n".join(f"[{item['doc_id']}] {item['text'][:500]}" for item in evidence)
    company = scenario.get("company", "")
    prompt = (
        f"根据证据为 {company} 一次性写出合规风险 JSON。"
        "字段：text, level, evidence_ids。"
        "尽量引用证据，但你也可以总结改写。\n\n"
        + packed
        + '\n\n输出：{"risks":[...]}'
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
    with urllib.request.urlopen(request, timeout=OLLAMA_TIMEOUT) as response:
        payload = json.loads(response.read().decode("utf-8"))
    raw = json.loads(payload["message"]["content"]).get("risks", [])
    try:
        return dump_risks(parse_risks(raw))
    except (ValidationError, ValueError):
        # 单次列允许脏输出：尽量吞下
        cleaned = []
        for item in raw if isinstance(raw, list) else []:
            if isinstance(item, dict) and item.get("text"):
                cleaned.append(
                    {
                        "text": str(item["text"]).strip(),
                        "level": "medium",
                        "evidence_ids": [str(x) for x in item.get("evidence_ids") or []],
                        "status": "assumption",
                    }
                )
        return cleaned


def _extractive(evidence: list[dict], scenario: dict) -> list[dict]:
    """优先用场景 facts 在证据中的原句，再补检索片段。"""
    risks: list[dict] = []
    used: set[str] = set()
    facts = [str(f) for f in (scenario.get("facts_from_source") or []) if str(f).strip()]
    for fact in facts:
        for item in evidence:
            snippet = None
            if fact in item["text"]:
                snippet = fact[:400]
            else:
                key = fact[:60]
                if len(key) >= 24 and key in item["text"]:
                    pos = item["text"].find(key)
                    snippet = item["text"][pos : pos + 400]
            if not snippet:
                continue
            risks.append(
                {
                    "text": snippet,
                    "level": "medium",
                    "evidence_ids": [item["doc_id"]],
                    "status": "assumption",
                }
            )
            used.add(item["doc_id"])
            break
    for item in evidence:
        if item["doc_id"] in used:
            continue
        risks.append(
            {
                "text": item["text"][:400],
                "level": "medium",
                "evidence_ids": [item["doc_id"]],
                "status": "assumption",
            }
        )
        if len(risks) >= 5:
            break
    return dump_risks(parse_risks(risks)) if risks else []


def _any_substring_ok(risks: list[dict], evidence: list[dict]) -> bool:
    by_id = {item["doc_id"]: item["text"] for item in evidence}
    for risk in risks:
        ids = risk.get("evidence_ids") or []
        if ids and all(doc_id in by_id and risk["text"] in by_id[doc_id] for doc_id in ids):
            return True
    return False


def analyze(state: dict) -> dict:
    started = time.perf_counter()
    evidence = state.get("evidence") or []
    if not evidence:
        risks = dump_risks(
            parse_risks(
                [
                    {
                        "text": "检索未命中可用证据，本轮不编造风险结论",
                        "level": "medium",
                        "evidence_ids": [],
                        "status": "missing",
                    }
                ]
            )
        )
        return {
            "risks": risks,
            "trace": _step(state, "analyze", "no_evidence_skip_model", hit_count=0, started=started),
        }

    notes: list[str] = []
    risks: list[dict] = []
    for attempt in (1, 2):
        try:
            raw = _ask_model_raw(evidence, state["scenario"])
            risks = dump_risks(parse_risks(raw))
            notes.append(f"model_ok_attempt{attempt}")
            break
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            notes.append(f"timeout_or_network:{type(exc).__name__}_attempt{attempt}")
            risks = []
        except (json.JSONDecodeError, ValidationError, ValueError, KeyError, TypeError) as exc:
            notes.append(f"schema_or_parse:{type(exc).__name__}_attempt{attempt}")
            risks = []
        except Exception as exc:  # noqa: BLE001 — 必须留下失败轨迹
            notes.append(f"model_failed:{type(exc).__name__}_attempt{attempt}")
            risks = []

    if not risks or not _any_substring_ok(risks, evidence):
        risks = _extractive(evidence, state["scenario"])
        notes.append("extractive_fallback")

    return {
        "risks": risks,
        "trace": _step(state, "analyze", "+".join(notes), hit_count=len(risks), started=started),
    }


def _scope_polarity(text: str) -> str | None:
    if _RESTRICTS_CROSS.search(text):
        return "restricts_cross_border"
    if _ALLOWS_CROSS.search(text):
        return "allows_cross_border"
    return None


def _has_opposing_scope(texts: list[str]) -> bool:
    polarities = {_scope_polarity(t) for t in texts}
    return "allows_cross_border" in polarities and "restricts_cross_border" in polarities


def verify(state: dict) -> dict:
    started = time.perf_counter()
    if state.get("skip_verify"):
        # 三列对照第 2 列：流水线但跳过校验
        return {
            "risks": state.get("risks") or [],
            "trace": _step(state, "verify", "skipped", hit_count=0, started=started),
        }

    by_id = {item["doc_id"]: item["text"] for item in state.get("evidence") or []}
    checked: list[dict] = []
    for risk in state.get("risks") or []:
        try:
            risk = parse_risks([risk])[0].model_dump()
        except (ValidationError, ValueError):
            checked.append(
                {
                    "text": str(risk.get("text") or "invalid risk"),
                    "level": "medium",
                    "evidence_ids": [],
                    "status": "assumption",
                }
            )
            continue
        if risk.get("status") == "missing":
            checked.append({**risk, "evidence_ids": [], "status": "missing"})
            continue
        ids = list(risk.get("evidence_ids") or [])
        existing = [doc_id for doc_id in ids if doc_id in by_id]
        substring_ok = [doc_id for doc_id in existing if risk["text"] in by_id[doc_id]]

        if (
            len(existing) >= 2
            and substring_ok
            and _has_opposing_scope([by_id[doc_id] for doc_id in existing])
        ):
            checked.append({**risk, "evidence_ids": existing, "status": "conflict"})
            continue
        if not substring_ok:
            checked.append({**risk, "evidence_ids": [], "status": "assumption"})
            continue
        checked.append({**risk, "evidence_ids": substring_ok, "status": "supported"})

    supported_idx = [i for i, item in enumerate(checked) if item["status"] == "supported"]
    flip: set[int] = set()
    for a, i in enumerate(supported_idx):
        for j in supported_idx[a + 1 :]:
            texts = [
                by_id[x]
                for x in checked[i]["evidence_ids"] + checked[j]["evidence_ids"]
                if x in by_id
            ]
            if _has_opposing_scope(texts):
                flip.add(i)
                flip.add(j)
    for i in flip:
        checked[i] = {**checked[i], "status": "conflict"}

    checked = dump_risks(parse_risks(checked)) if checked else []
    supported = sum(item["status"] == "supported" for item in checked)
    conflicts = sum(item["status"] == "conflict" for item in checked)
    return {
        "risks": checked,
        "trace": _step(
            state,
            "verify",
            f"supported={supported}/{len(checked)} conflict={conflicts}",
            hit_count=supported,
            started=started,
        ),
    }


def write_report(state: dict) -> dict:
    started = time.perf_counter()
    scenario = state["scenario"]
    company = str(scenario.get("company") or "").strip() or "（未填公司）"
    profile = state.get("profile") or {}
    risks = state.get("risks") or []
    supported = [item for item in risks if item["status"] == "supported"]
    conflicts = [item for item in risks if item["status"] == "conflict"]
    assumptions = [item for item in risks if item["status"] == "assumption"]
    missing = [item for item in risks if item["status"] == "missing"]
    questions = list(state.get("questions") or [])
    by_id = {item["doc_id"]: item for item in state.get("evidence") or []}

    lines = [
        "# 合规预审报告",
        "",
        "这不是法律意见。语料有限，结论需要人工复核。",
        "",
        "## 场景摘要",
        f"{company}：基于公开材料的预审摘要（业务类型={profile.get('business_type') or '未填'}，法域={profile.get('region') or '未填'}）。",
        "",
        "## 适用范围与材料来源",
        "检索命中的片段见附录。未检索到的法域不写成已覆盖。",
        "",
        "## 数据流与关键处理活动",
        profile.get("flow") or "未提供可用事实。",
        "",
        "## 风险清单",
    ]
    if supported:
        for item in supported:
            lines.append(f"- （supported）{item['text']}")
    else:
        lines.append("- 没有能逐字对上原文且无冲突的风险结论。")
    if conflicts:
        lines.append("")
        lines.append("以下条目因适用范围相反标为 conflict（两边证据均保留，不自动判赢）：")
        for item in conflicts:
            cite = ", ".join(item.get("evidence_ids") or [])
            lines.append(f"- （conflict）{item['text'][:300]} ［证据: {cite}］")
            for doc_id in item.get("evidence_ids") or []:
                ev = by_id.get(doc_id)
                if ev:
                    lines.append(f"  - {doc_id}: {ev['text'][:220]}")

    lines.extend(["", "## 信息缺口与冲突"])
    wrote = False
    for item in conflicts:
        lines.append(f"- （conflict）证据适用范围可能相反，请人工复核：{item['text'][:180]}")
        wrote = True
    for item in missing:
        lines.append(f"- （missing）{item['text']}")
        wrote = True
    for q in questions:
        if not any(q == item["text"] for item in missing):
            lines.append(f"- （missing）{q}")
            wrote = True
    if assumptions:
        for item in assumptions:
            lines.append(f"- （assumption）模型给出的句子对不上证据原文：{item['text'][:180]}")
            wrote = True
    if not wrote:
        lines.append("- 本轮没有被降级或冲突的句子。")

    lines.extend(
        [
            "",
            "## 建议与人工复核项",
            "请对照附录里的原文，确认是否还需要合同、评估或告知同意。冲突条目不要自动采信任一侧。",
            "",
            "## 附录：引用片段列表",
        ]
    )
    if state.get("evidence"):
        for item in state["evidence"]:
            lines.append(f"- {item['doc_id']} | {item['title']} | {item['url']}")
    else:
        lines.append("- （无）")
    report = "\n".join(lines) + "\n"
    return {
        "report": report,
        "trace": _step(state, "write_report", f"sections={len(REPORT_SECTIONS)}", started=started),
    }


def after_understand(state: dict) -> Literal["hold", "retrieve"]:
    if state.get("questions"):
        return "hold"
    return "retrieve"


def build_graph():
    builder = StateGraph(GraphState)
    for name, fn in [
        ("understand", understand),
        ("hold", hold),
        ("retrieve", retrieve),
        ("analyze", analyze),
        ("verify", verify),
        ("write_report", write_report),
    ]:
        builder.add_node(name, fn)
    builder.add_edge(START, "understand")
    builder.add_conditional_edges("understand", after_understand)
    builder.add_edge("hold", END)
    builder.add_edge("retrieve", "analyze")
    builder.add_edge("analyze", "verify")
    builder.add_edge("verify", "write_report")
    builder.add_edge("write_report", END)
    return builder.compile()


def apply_supplements(scenario: dict, supplements: dict | None) -> dict:
    if not supplements:
        return scenario
    merged = dict(scenario)
    for key, value in supplements.items():
        if value is None:
            continue
        merged[key] = value
    return merged


def run_scenario_dict(
    scenario: dict,
    supplements: dict | None = None,
    *,
    index: HybridIndex | None = None,
    skip_verify: bool = False,
) -> dict:
    scenario = apply_supplements(dict(scenario), supplements)
    hybrid = index or HybridIndex(load_chunks())
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
            "index": hybrid,
            "held": False,
            "skip_verify": skip_verify,
        }
    )


def run_scenario(
    scenario_path: Path,
    supplements: dict | None = None,
    *,
    index: HybridIndex | None = None,
    skip_verify: bool = False,
) -> dict:
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    return run_scenario_dict(
        scenario, supplements=supplements, index=index, skip_verify=skip_verify
    )
