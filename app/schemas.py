"""P10 各步骤之间的结构化交接。图的状态用这些模型的 model_dump()。"""

from typing import Literal

from pydantic import BaseModel, Field

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
    region: str
    doc_type: str
    title: str
    text: str
    url: str
    score: float = 0.0


class RiskItem(BaseModel):
    text: str
    level: Literal["low", "medium", "high"]
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
