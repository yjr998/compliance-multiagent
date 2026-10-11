"""FastAPI：跑场景、补填续跑、读报告。"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.rag.corpus import ROOT, load_chunks
from app.rag.index import HybridIndex
from app.workflow import run_scenario_dict

WEB_DIR = ROOT / "web"
SCENARIO_DIR = ROOT / "data" / "scenarios"
REPORT_DIR = ROOT / "data" / "reports"
TRACE_DIR = ROOT / "data" / "traces"

PRESETS = {
    "aliyun": "aliyun-cloud.json",
    "shein": "shein.json",
    "slack": "slack.json",
}

_SAFE_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


class ScenarioIn(BaseModel):
    company: str = ""
    region: str = ""
    business_type: str = ""
    service_mode: str = ""
    data_types: list[str] = Field(default_factory=list)
    cross_border: bool | None = None
    facts_from_source: list[str] = Field(default_factory=list)
    source_url: str = ""
    id: str = "custom"


class RunRequest(BaseModel):
    preset: str | None = None
    scenario: ScenarioIn | None = None
    supplements: dict[str, Any] = Field(default_factory=dict)
    save_as: str | None = None


class RunResponse(BaseModel):
    held: bool
    questions: list[str]
    profile: dict
    risks: list[dict]
    evidence: list[dict]
    trace: list[dict]
    report: str
    saved_as: str | None = None


@lru_cache(maxsize=1)
def get_index() -> HybridIndex:
    return HybridIndex(load_chunks())


def create_app() -> FastAPI:
    app = FastAPI(
        title="ComplianceFlow",
        description="P10 合规预审流水线 API",
        version="0.1.0",
    )

    if WEB_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/", response_class=HTMLResponse)
    def home() -> HTMLResponse:
        index = WEB_DIR / "index.html"
        if not index.is_file():
            return HTMLResponse("<p>web/index.html missing</p>", status_code=500)
        return HTMLResponse(index.read_text(encoding="utf-8"))

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "chunks": len(get_index().chunks)}

    @app.get("/api/scenarios")
    def list_scenarios() -> list[dict]:
        rows = []
        for key, filename in PRESETS.items():
            path = SCENARIO_DIR / filename
            data = json.loads(path.read_text(encoding="utf-8"))
            rows.append(
                {
                    "id": key,
                    "company": data.get("company"),
                    "region": data.get("region"),
                    "business_type": data.get("business_type"),
                    "source_url": data.get("source_url"),
                    "facts_count": len(data.get("facts_from_source") or []),
                }
            )
        return rows

    @app.get("/api/scenarios/{preset_id}")
    def get_scenario(preset_id: str) -> dict:
        filename = PRESETS.get(preset_id)
        if not filename:
            raise HTTPException(404, f"unknown preset: {preset_id}")
        return json.loads((SCENARIO_DIR / filename).read_text(encoding="utf-8"))

    @app.post("/api/run", response_model=RunResponse)
    def run(req: RunRequest) -> RunResponse:
        if req.preset:
            filename = PRESETS.get(req.preset)
            if not filename:
                raise HTTPException(400, f"unknown preset: {req.preset}")
            scenario = json.loads((SCENARIO_DIR / filename).read_text(encoding="utf-8"))
            default_name = {"aliyun-cloud.json": "aliyun", "shein.json": "shein", "slack.json": "slack"}[
                filename
            ]
        elif req.scenario is not None:
            scenario = req.scenario.model_dump()
            default_name = "custom"
        else:
            raise HTTPException(400, "provide preset or scenario")

        state = run_scenario_dict(scenario, supplements=req.supplements or None, index=get_index())
        save_as = req.save_as or default_name
        if not _SAFE_NAME.match(save_as):
            raise HTTPException(400, "save_as must be [a-zA-Z0-9_-]{1,64}")

        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        TRACE_DIR.mkdir(parents=True, exist_ok=True)
        (REPORT_DIR / f"{save_as}.md").write_text(state["report"], encoding="utf-8")
        trace_payload = {
            "held": bool(state.get("held")),
            "questions": state.get("questions") or [],
            "trace": state["trace"],
            "risks": state["risks"],
            "evidence": [
                {"doc_id": item["doc_id"], "title": item["title"], "score": item["score"]}
                for item in state.get("evidence") or []
            ],
        }
        (TRACE_DIR / f"{save_as}.json").write_text(
            json.dumps(trace_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        evidence = [
            {
                "doc_id": item["doc_id"],
                "title": item["title"],
                "score": item["score"],
                "url": item.get("url", ""),
                "text": (item.get("text") or "")[:240],
            }
            for item in state.get("evidence") or []
        ]
        return RunResponse(
            held=bool(state.get("held")),
            questions=list(state.get("questions") or []),
            profile=state.get("profile") or {},
            risks=state.get("risks") or [],
            evidence=evidence,
            trace=state.get("trace") or [],
            report=state.get("report") or "",
            saved_as=save_as,
        )

    @app.get("/api/reports")
    def list_reports() -> list[str]:
        if not REPORT_DIR.is_dir():
            return []
        return sorted(p.stem for p in REPORT_DIR.glob("*.md"))

    @app.get("/api/reports/{name}")
    def get_report(name: str) -> PlainTextResponse:
        if not _SAFE_NAME.match(name):
            raise HTTPException(400, "bad name")
        path = REPORT_DIR / f"{name}.md"
        if not path.is_file():
            raise HTTPException(404, "report not found")
        return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="text/markdown; charset=utf-8")

    @app.get("/api/reports/{name}/download")
    def download_report(name: str) -> FileResponse:
        if not _SAFE_NAME.match(name):
            raise HTTPException(400, "bad name")
        path = REPORT_DIR / f"{name}.md"
        if not path.is_file():
            raise HTTPException(404, "report not found")
        return FileResponse(path, filename=f"{name}.md", media_type="text/markdown")

    @app.get("/api/traces/{name}")
    def get_trace(name: str) -> dict:
        if not _SAFE_NAME.match(name):
            raise HTTPException(400, "bad name")
        path = TRACE_DIR / f"{name}.json"
        if not path.is_file():
            raise HTTPException(404, "trace not found")
        return json.loads(path.read_text(encoding="utf-8"))

    return app


app = create_app()
