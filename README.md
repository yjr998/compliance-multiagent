# Compliance multi-agent

面向全球业务拓展场景的多智能体协同分析与合规预审报告生成（CityU FYP / P10）。

固定五步流水线：场景理解 → 混合检索 → 风险分析 → **代码侧证据校验** → 报告生成。引用对不上原文会降级；报告不是法律意见，正式结论需人工复核。完成标准见 [`Target.md`](Target.md)。

当前可跑通的是 **阿里云国际站** 场景（本机 Ollama `qwen2.5:7b`）。

## 目录

| 路径 | 说明 |
|------|------|
| `app/` | 工作流、Schema、RAG |
| `scripts/` | `run_aliyun.py` / `run_eval.py` |
| `data/corpus/` | 公开语料（隐私政策、法规摘录等） |
| `data/scenarios/` | 场景输入 JSON |
| `data/reports/`、`data/traces/`、`data/eval/` | 示例报告、轨迹与检索评测 |
| `docs/` | 设计笔记 |

## 环境

- Python 3.11+（本机曾用 3.13）
- [Ollama](https://ollama.com/) 并拉取模型，例如：`ollama pull qwen2.5:7b`

```powershell
git clone https://github.com/yjr998/compliance-multiagent.git
cd compliance-multiagent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

macOS / Linux：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 运行

在仓库根目录执行（把 `PYTHONPATH` 指到本仓库根）：

```powershell
$env:PYTHONPATH = (Get-Location).Path
.\.venv\Scripts\python.exe scripts\run_eval.py
.\.venv\Scripts\python.exe scripts\run_aliyun.py
```

- 报告：`data/reports/aliyun.md`
- 轨迹：`data/traces/aliyun.json`
- 检索评测：`data/eval/result.json`

向量索引会写在本地（见 `.gitignore` 中的 `data/index/`、`.chroma/`），不提交仓库。

## 说明

语料来自公开网页/法规摘录，仅供研究演示。输出不构成法律意见。
