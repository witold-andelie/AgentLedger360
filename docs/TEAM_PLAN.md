# 半天黑客松作战计划（两台电脑）

## 1. 一句话
**AI 智能体在市场里互相买卖“市场情报”**：买方 agent 通过 agent card 发现卖方 → HTTP 402 报价 → 托管付款 →
收到数据后按合同自动验收 → 结算或发起争议，由确定性仲裁重跑验收决定退款 → 信誉更新 → 所有事件进入数仓，
产出 Customer 360、agent 可靠性和数据质量报表。

| 评审要求（Case 02） | 我们的实现 |
|---|---|
| Agent-to-agent discovery | `/.well-known/agents.json` agent card + 注册中心按 信誉−价格 排名 |
| Payments | HTTP 402 报价 → 托管 → HMAC 收据作为 `X-Payment` 头 → 交付 |
| Wallets | 双分录账本、每个 agent 一个钱包、支出授权（单笔/日限额）、生存等级 |
| Dispute resolution | 仲裁者重算哈希 + 重跑验收；规则表决定全额/部分退款/驳回 |
| “不止于此” | 信誉随结果变化、事件溯源数仓、9 项数据质量与对账、LLM 只解释不动钱 |

## 2. 相对原提纲的取舍（半天版）

| 原提纲（2 天） | 半天版 | 理由 |
|---|---|---|
| PostgreSQL | SQLite（core.db + attach analytics.db） | 零安装；两个 schema 的 OLTP/OLAP 分层保留 |
| Kafka | outbox 表 + 游标轮询（同样的契约） | 演示稳定；面试时讲“可 1:1 换成 Kafka consumer” |
| Airflow | `analytics/pipeline.py` 拓扑 DAG + 运行日志 | 同样有任务依赖、幂等、失败传播 |
| LangGraph | 普通 Python 状态机 + 可选 Claude | 学习成本为零；LLM 只解释（R1） |
| CSV 清洗服务 | 股票信号/特征/行情服务（zoomcamp） | 验收可以量化（命中率、Rank IC），争议有客观依据 |
| Streamlit | React + Vite 前端，FastAPI 托管，部署 Render | 与你 EuroGoal 项目同一套路，可直接复用经验 |
| K8s | 不做 | Render Blueprint 足够 |

## 3. 分工（以 OPM SD4 为准）

| | Dev A / 笔记本 A | Dev B / 笔记本 B |
|---|---|---|
| Python | **3.11**（`.venv311`） | **3.13**（`.venv313`） |
| 负责 | `economy/` `agents/` `platform_api.py` `runner.py` `server.py` `sellers/app.py` `Dockerfile` `render.yaml` | `market/` `sellers/catalog.py` `analytics/` `sql/marts` `sql/quality_checks.sql` `sql/002_analytics.sql` `frontend/` |
| 共同 | `contracts.py`、`sql/001_core.sql`、`docs/opm/*`（R15：两人一起改） | 同左 |

两台机器用不同 Python 版本，**每次合并天然就做了一次 3.11/3.13 兼容测试**。

## 4. 时间表（约 5.5 小时）

| 时间 | A | B |
|---|---|---|
| 0:00–0:30 | 一起：建 GitHub 私有仓库、两台机器跑通 `check_compat`、通读 OPM、确认契约冻结 | 同左 |
| 0:30–2:00 | 托管超时退款（CANCELLED）、卖方签名交付、Render 首次部署 | 前端 Market 页（按 FRONTEND_RULES）、信号调参 |
| 2:00–2:30 | 联调：前端 ↔ `/api/round`，双机模式（B 跑 sellers） | 同左 |
| 2:30–4:00 | 可选：价格协商、LLM 解释开关 | Agents / Customer360 / DataQuality 页 |
| 4:00–4:45 | Render 部署（单服务）、预热、录屏备份 | 截图、README 数字、OPM 图放进 slides |
| 4:45–5:30 | 彩排 3 分钟 demo + 面试话术 | 同左 |

**砍需求顺序**（时间不够时从上往下砍）：价格协商 → LLM → 双机/双服务模式 → 卖方签名 → 超时退款 → 前端第 2–4 页。
**永远不砍**：Market 页演示、争议退款、对账与 DQ 全绿、3.11/3.13 双绿。

## 5. Git 规则
- `main` 永远可演示；各自分支 `a/*`、`b/*`，**每小时合并一次**，合并前跑 `scripts/check_compat.*`。
- `AgentLedger360_Case02_Architecture_Python311_313.md` 只在本地（已在 `.gitignore` / `.dockerignore`）。
- 改契约/状态/事件 → 同一个提交里更新 `docs/opm/agentledger_opm.dot` + `OPM_GUIDE.md` 并重新渲染。

## 6. 3 分钟演示脚本
1. （20s）问题：agent 之间要交易数据/服务，需要发现、付款、验收、纠纷处理，而且要可审计。
2. （60s）Market 页点 “Run market round”：最便宜的 `sig-hype` 被选中 → 数据过期 → **全额退款**；
   `sig-rsi` 表现不达标 → **50% 退款**；`sig-momentum` → **成交**。再点一次：hype 信誉下降，不再被选中。
3. （40s）Agents 页：信誉、成功率、延迟（= IT 运维分析）；Customer 360 + RFM（= SAP CPIT Customer 360）。
4. （30s）Data quality 页：9 项检查全绿、托管余额 = 未结订单（对账）、事件流可重放。
5. （30s）OPM 图一张：LLM 只解释不动钱（R1），状态变更与事件同事务（R3），3.11/3.13 双绿。

## 7. 和 SAP iXp（IT Data & Analytics, CPIT, Customer 360 / BDC）的对应
- **SQL（必备）**：窗口函数（最新状态、RFM 的 NTILE）、CTE、对账查询、DQ 检查都是手写 SQL。
- **数据管道**：outbox → raw_events（去重、游标）→ dim/fact → KPI 视图；幂等重建；运行日志。
- **Customer 360**：`v_customer_360` + `v_customer_rfm`（复用你 golden_dragon_prague 的 RFM 写法）。
- **云基础设施分析**：卖方延迟、成功率、争议率 = 服务可靠性指标。
- **AI 原型**：agent 经济 + 可选 Claude，并且有治理边界（R1）。
- **治理 / PO 支持**：OPM 模型、规则表 R1–R16、DoD、兼容门禁。
- 措辞：只说“概念上对应 BDC 的 data product / 数据契约”，**不声称与任何 SAP 产品集成**。

## 8. 借鉴来源（已扫描你的 30 个仓库 + 97 个星标）

| 来源 | 借鉴点 | 落地位置 |
|---|---|---|
| DataTalksClub/stock-markets-analytics-zoomcamp | M1 数据源、M2 特征（growth_Nd、RSI…）、M3 方向预测、M4 回测与手续费、M5 脚本化+SQLite+调度 | `market/*`、`analytics/pipeline.py` |
| witold-andelie/stock_analysis_wentao（HW2） | RSI<30 超卖入场策略 | `signals.rsi_reversion`（卖方 sig-rsi） |
| witold-andelie/golden_dragon_prague | RFM 分群（NTILE）、星型模型、DQ 过程、面试指南写法 | `v_customer_rfm`、本文第 7 节 |
| witold-andelie/quant-alpha-foundation | IC / 稳健性诊断、合成数据回退、Bruin 拓扑执行、CI | `backtest.rank_ic`、`data.py`、`pipeline.py` |
| witold-andelie/PerpPulse | 证据哈希、对账记分卡、as-of 截点、不夸大的验证记录 | `disputes.py`、`quality_checks.sql`、README “Honest limits” |
| witold-andelie/revio | LLM 编排 + 确定性分析器，证据驱动结论 | R1：LLM 只解释，规则表裁决 |
| EuroGoal（football match prediction） | React+Vite 前端、i18n、Docker 两阶段构建、Render Blueprint | `frontend/`、`Dockerfile`、`render.yaml` |
| Conway-Research/automaton | 余额决定“生存等级”、钱包即身份、宪法式规则 | `buyer.TIERS`、规则表 |
| HKUDS/AI-Trader | agent 读 SKILL.md 自助接入、信号发布与积分 | `/SKILL.md`、`/.well-known/agents.json` |
| TauricResearch/TradingAgents | 分析师角色分工、point-in-time 防前视 | 卖方人设、`point_in_time` 检查 |
| gplearn / GPLearnFinance3D / AlphaMaster | IC、IR、RankIC 因子评价 | 验收条款 `min_rank_ic` |
| freqtrade | dry-run / 手续费建模 | `backtest.fee_bps` |
| Coral-Protocol/AgentRadio | 共享频道被动感知 | 可选扩展：买方订阅 `reputation.updated` 事件 |
| tt-a1i/archify、Recordly / openscreen | 架构图、录屏 | slides 与 demo 备份视频 |

## 9. 风险与预案
| 风险 | 预案 |
|---|---|
| 会场网络差 / Render 休眠 | 本地 `python -m agentledger.demo` 与本地前端随时可演示；提前录屏 |
| yfinance 限流 | 默认 synthetic（确定性、离线） |
| 双机网络不通 | 单机 in-process 模式功能完全一致 |
| LLM 无额度 | 默认 `AL_LLM=0`，所有路径确定性 |
