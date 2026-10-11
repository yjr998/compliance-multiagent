# 三场景期望风险点与样例说明

> 用途：人工对照清单。系统报告不必逐字相同，但 **主题应被覆盖或明确标成 missing/assumption**。  
> 样例报告：`data/reports/{aliyun,shein,slack}.md`  
> 最近一次自动主题勾选：`scripts/run_eval.py`（`theme:*` 用例）于 2026-10-11，**50/50 全过**。  
> 输入场景：`data/scenarios/*.json`（事实只允许来自公开页原句）。

---

## 共用规则

1. 每条重要结论尽量能指回原文子串；对不上 → `assumption`。  
2. 证据适用范围相反 → `conflict`，两边都列，不自动判赢。  
3. 关键字段缺失 → `hold`，不硬编风险。  
4. 报告开头必须声明：不是法律意见，需要人工复核。  
5. 七章结构见 `Target.md` / `app/schemas.py` 的 `REPORT_SECTIONS`。

---

## 1. 阿里云国际站（`aliyun-cloud`）

**材料：** 国际站隐私政策（新加坡主体、第三方可能在新加坡境内外、PRC 机房收集 photo ID）。

| ID | 期望风险点（主题） | 勾选 | 依据（报告位置） |
| --- | --- | --- | --- |
| A1 | 新加坡缔约主体处理签约人身份/邮箱/手机 | ✅ | 数据流含 Singapore Private Limited + signatory；风险清单亦出现主体名 |
| A2 | 第三方服务商可能在新加坡以外 | ✅ | 数据流 + supported「Singapore or outside of Singapore」 |
| A3 | 选用中国大陆机房时收集证件类敏感信息 | ✅ | 数据流含 photo ID |
| A4 | 跨境场景对照 PDPA / PIPL | ✅ | 附录含 `pipl-*`（及检索侧 PDPA 语料） |

**样例报告：** `data/reports/aliyun.md`  
**人工抽查：** 数据流来自 `facts_from_source` ✅；未编造未公开内部流程 ✅

---

## 2. SHEIN（`shein`）

| ID | 期望风险点（主题） | 勾选 | 依据 |
| --- | --- | --- | --- |
| S1 | 新加坡运营主体披露 | ✅ | 数据流 / 风险含 Roadget Business Pte. Ltd. |
| S2 | 个人数据可能跨境至美/中/新 | ✅ | 数据流含 United States, China and/or Singapore |
| S3 | 不编支付卡风险 | ✅ | 报告无 credit card / 支付卡（场景 `not_in_fetched_text`） |
| S4 | 对照 PDPA / PIPL / GDPR 语料 | ✅ | 附录含 pipl；评测检索含 PDPA/GDPR |

**样例报告：** `data/reports/shein.md`  
**缺信息：** `shein-missing` hold ✅ → `shein-resumed` 续跑 ✅  
**人工抽查：** 无阿里云隐私页串用为 SHEIN 事实 ✅

---

## 3. Slack（`slack`）

| ID | 期望风险点（主题） | 勾选 | 依据 |
| --- | --- | --- | --- |
| L1 | 客户数据可能存于所选区域外 | ✅ | 数据流 / 风险含 stored outside this data region |
| L2 | 托管方 AWS，地点含新加坡 | ✅ | Amazon Web Services + Singapore |
| L3 | Edge 多区域传输 | ✅ | Edge region 出现在数据流与风险 |
| L4 | 禁止 Automotive Cloud 一般化 | ✅ | 全文无 `Automotive` |
| L5 | GovSlack 适用范围限定 | ✅ | 出现 GovSlack 且带 excluding / (b) 语境 |

**样例报告：** `data/reports/slack.md`

---

## 评测怎么用这份清单

- **≥30 用例：** `scripts/run_eval.py` → `data/eval/result.json`（当前 **50/50**，含检索 15/15）  
- **三列对照：** `scripts/run_ablation.py` → `data/eval/ablation.json`  
- **主题覆盖：** 上表勾选 + `theme:*` 自动用例；未覆盖记 Discussion 失败案例
