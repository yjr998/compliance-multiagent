"""P10 各步骤之间的结构化交接。图的状态用这些模型的 model_dump()。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

RiskStatus = Literal["supported", "assumption", "missing", "conflict"]


class BusinessProfile(BaseModel):
    region: str = ""
    business_type: str = ""
    data_types: list[str] = Field(default_factory=list)
    cross_border: bool | None = None
    flow: str = ""
    service_mode: str = ""
    gaps: list[str] = Field(default_factory=list)


class EvidenceHit(BaseModel):
    doc_id: str
    region: str = ""
    doc_type: str = ""
    title: str = ""
    text: str
    url: str = ""
    score: float = 0.0


class RiskItem(BaseModel):
    text: str
    level: Literal["low", "medium", "high"] = "medium"
    evidence_ids: list[str] = Field(default_factory=list)
    status: RiskStatus = "assumption"


class ReportSection(BaseModel):
    name: str
    body: str
    citations: list[str] = Field(default_factory=list)


class TraceStep(BaseModel):
    node: str
    elapsed_ms: int = 0
    note: str = ""
    hit_count: int = 0


REPORT_SECTIONS = [
    "场景摘要",
    "适用范围与材料来源",
    "数据流与关键处理活动",
    "风险清单",
    "信息缺口与冲突",
    "建议与人工复核项",
    "附录：引用片段列表",
]


def parse_risks(raw: Any) -> list[RiskItem]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("risks must be a non-empty list")
    items: list[RiskItem] = []
    for i, row in enumerate(raw):
        if not isinstance(row, dict):
            raise ValueError(f"risk[{i}] not object")
        level = row.get("level") if row.get("level") in {"low", "medium", "high"} else "medium"
        status = (
            row.get("status")
            if row.get("status") in {"supported", "assumption", "missing", "conflict"}
            else "assumption"
        )
        item = RiskItem(
            text=str(row.get("text") or "").strip(),
            level=level,  # type: ignore[arg-type]
            evidence_ids=[str(x) for x in (row.get("evidence_ids") or [])],
            status=status,  # type: ignore[arg-type]
        )
        if not item.text:
            raise ValueError(f"risk[{i}] blank text")
        items.append(item)
    return items


def parse_evidence(raw: list[dict]) -> list[EvidenceHit]:
    return [EvidenceHit.model_validate(row) for row in raw]


def dump_risks(items: list[RiskItem]) -> list[dict]:
    return [item.model_dump() for item in items]


def dump_evidence(items: list[EvidenceHit]) -> list[dict]:
    return [item.model_dump() for item in items]


def dump_trace_step(node: str, note: str = "", hit_count: int = 0, elapsed_ms: int = 0) -> dict:
    return TraceStep(node=node, note=note, hit_count=hit_count, elapsed_ms=elapsed_ms).model_dump()


__all__ = [
    "BusinessProfile",
    "EvidenceHit",
    "RiskItem",
    "ReportSection",
    "TraceStep",
    "REPORT_SECTIONS",
    "ValidationError",
    "parse_risks",
    "parse_evidence",
    "dump_risks",
    "dump_evidence",
    "dump_trace_step",
]
