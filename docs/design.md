# 设计草稿

范围以 `Target.md` 为准。这一页只把流水线和字段定下来，还没有业务代码。

## 流水线

```text
场景表
  → understand（整理字段，缺了就列出问题）
  → retrieve（混合检索，不调模型）
  → analyze（按证据列风险，输出 JSON）
  → verify（代码核对引用是不是原文子串）
  → write_report（固定 7 章）
```

`understand` 发现缺口时先到 `ask_user`，补完再进入 `retrieve`。

## 字段

见 `app/schemas.py`：`BusinessProfile`、`EvidenceHit`、`RiskItem`、`ReportSection`、`TraceStep`。

风险状态只有 `supported`、`assumption`、`missing`、`conflict`。

## 模型

本机 RTX 4060 8GB。推理用 Ollama 的 `qwen2.5:7b`。模型文件放在 `D:\FYP\models`，不进项目仓库。

## 语料

只收带 URL 的原文。清单在 `data/corpus/catalog.json`。
