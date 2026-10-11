# Compliance multi-agent

P10 的项目目录。完成标准在 `Target.md`。

当前：混合检索、五步流水线（**Pydantic Schema 交接**）、代码校验（含 `conflict`）、缺信息 hold、失败重试/超时降级、三场景报告、**评测 50/50**、**三列对照 74.9%→0.0%**、FastAPI + Web。

默认模型 `qwen2.5:7b`；本机可设 `$env:COMPLIANCE_MODEL="qwen2.5:3b"`。

## 安装

```powershell
cd D:\FYP\FYP\compliance-multiagent
$env:PYTHONPATH = "D:\FYP\FYP\compliance-multiagent"
D:\conda\python.exe -m pip install -r requirements.txt
```

另需本机 Ollama 与模型。

## 命令

```powershell
cd D:\FYP\FYP\compliance-multiagent
$env:PYTHONPATH = "D:\FYP\FYP\compliance-multiagent"
$env:COMPLIANCE_MODEL = "qwen2.5:3b"

D:\conda\python.exe scripts\run_eval.py          # ≥30（当前 50）用例
D:\conda\python.exe scripts\run_ablation.py      # 三列对照 → data/eval/ablation.json
D:\conda\python.exe scripts\run_scenario.py --all
D:\conda\python.exe scripts\run_web.py           # http://127.0.0.1:8000
```

## 文档

| 文档 | 路径 |
| --- | --- |
| 范围一页纸 | `Target.md` |
| 架构图 | `docs/architecture.md` |
| 期望风险点（已勾） | `docs/expected_risks.md` |
| 简历子弹 | `docs/resume_bullets.md` |
| 设计 | `docs/design.md` |

## 产出

| 产出 | 路径 |
| --- | --- |
| 报告 | `data/reports/{aliyun,shein,slack}.md` |
| 评测 | `data/eval/result.json`（50/50，检索 15/15） |
| 三列对照 | `data/eval/ablation.json`（74.9% → 0.0%） |
| Web / API | `http://127.0.0.1:8000/` · `/docs` |

## 局限

- 不是法律意见；语料有限，结论需人工复核。  
- 三列对照 B/C 使用同一批风险声明（含 1 条探针幻觉），口径写在 `ablation.json`。  
- 换模型后请重跑 `run_ablation.py`，简历百分比以新文件为准。
