# 设计草稿

范围以 `Target.md` 为准。这一页只把流水线和字段定下来，还没有业务代码。

## 流水线

```text
场景表
  → understand（从 scenario 读字段；缺关键项列出 questions）
      ├─ hold（缺公司名/事实/法域/业务类型 → 停，不硬编风险）
      └─ retrieve → analyze → verify（子串 + conflict）→ write_report
```

缺信息闭环：`hold` 返回 `questions`；用户用 `--supplement key=value` 或 Web/API 补填后续跑。

一页架构图见 `docs/architecture.md`。期望风险点见 `docs/expected_risks.md`。

## 接口

- CLI：`scripts/run_scenario.py`、`scripts/run_eval.py`、`scripts/run_ablation.py`
- Web / API：`scripts/run_web.py` → `app/api.py`（`POST /api/run`）

## Schema 与失败行为

- 步骤间：`BusinessProfile` / `EvidenceHit` / `RiskItem` / `TraceStep`（`app/schemas.py`）
- 模型 JSON 不合 Schema：重试一次 → 仍失败则抽取式降级，note 写入 trace
- 超时/网络错误：同上，trace 记 `timeout_or_network:*`
- 检索空：`missing`，不调模型
- 缺关键字段：`hold`，不硬编风险

## 字段

见 `app/schemas.py`：`BusinessProfile`、`EvidenceHit`、`RiskItem`、`ReportSection`、`TraceStep`。

风险状态只有 `supported`、`assumption`、`missing`、`conflict`。

## 模型

本机 RTX 4060 8GB。推理用 Ollama 的 `qwen2.5:7b`。模型文件放在 `D:\FYP\models`，不进项目仓库。

## 语料

只收带 URL 的原文。清单在 `data/corpus/catalog.json`。
