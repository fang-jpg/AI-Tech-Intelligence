# AI-Tech-Intelligence（高校研究机构恢复版）

本工作区依据共享会话中“高校科研机构”工作表遗留数据，重建了 99 个实体的注册表、官方源搜索、证据约束量化研判和 Excel 导出流程。

## 本轮结果

- 51 个高校 / 研究机构，48 位研究者。
- 304 条来源记录；83 个实体具有当前官方搜索线索，16 个只有注册表基线。
- 99 条实体级量化研判，实际分析模型为 `qwen3.7-plus`。
- 趋势精确重复 0 条；最高两两相似度 0.386（复核阈值 0.62）。
- 证据不足项的概率上界强制不超过 45%。

最终工作簿位于：

`outputs/高校研究机构智能情报_20260922/高校研究机构_AI技术情报量化研判_20260922.xlsx`

## 运行顺序

Windows PowerShell 的脚本执行策略可能拦截 `npm.ps1`，可直接使用 Node：

```powershell
npm.cmd install --no-audit --no-fund
node scripts/build_academic_registry.mjs
node scripts/collect_academic_intelligence.mjs
node scripts/analyze_academic_outlooks.mjs
node scripts/export_academic_workbook.mjs
node scripts/verify_academic_workbook.mjs
```

搜索和分析分别读取 `.env.txt` 中已配置的 `TAVILY_API_KEY` / `SERPER_API_KEY` 与 `GENERAL_AI_REPORT_LLM_*`。脚本不会把密钥写入 JSON、Excel 或日志。

## 关键文件

- `config/companies.yaml`：99 个实体及官方域名白名单。
- `config/people.yaml`：48 位个人研究者注册表。
- `config/sources.yaml`：官网、个人主页和官方 GitHub 来源。
- `data/academic_web_search_20260922.json`：搜索查询、来源摘录与发现方式。
- `data/academic_quantitative_outlooks_20260922.json`：量化研判、原始阈值和质量指标。
- `skills/executive-intelligence/SKILL.md`：证据、归因、量化与去重规则。

## 量化口径

概率区间是模型在给定官方摘录基础上的主观分析，不是统计频率或机构承诺。每条判断同时包含预测窗口、成熟度、领先指标、可核验阈值、反向信号和证伪条件。若来源没有数值基线，系统不会虚构性能提升百分比。

本轮内容基础主要是官方搜索摘录，并非所有页面的完整正文。重要结论应打开工作簿中的官方链接阅读全文复核。
