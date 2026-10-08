# AgentLedger 360 — OPM 规则框架指南（给接手的 agent / 开发者）

本目录是项目的**系统模型单一事实源**（single source of truth）：

| 文件 | 作用 |
|---|---|
| `agentledger_opm.dot` | OPM 图（ISO 19450 记法，Graphviz DOT）。**改模型只改这个文件** |
| `agentledger_opm.svg` | 全图（所有 OPD + 图例 + 规则表） |
| `opm_SD.svg` … `opm_SD4.svg` | 每个 OPD 单独一张，方便阅读 |
| `OPM_GUIDE.md`（本文） | OPL 文本、事物→代码映射、规则→测试映射、接手流程 |

重新渲染：`python scripts/render_opm.py`（需要 Graphviz `dot`）。

---

## 0. 接手 agent 的工作流（必须遵守）

1. **先读 SD，再按虚线 "in-zoomed in" 往下读**：SD → SD1（交易）→ SD2（争议）→ SD3（分析）→ SD4（开发部署）。
2. **动代码前**：在 DOT 里找到你要改的过程（椭圆），看它的灰色小字（实现模块）和橙色标签 `[R…]`（必须遵守的规则）。
3. **改代码后**，如果改变了下列任何一项，**同一个提交里**同步更新 `agentledger_opm.dot` + 本文 + 重新渲染：
   - 新增/删除/重命名过程、对象或状态（例如新增 `CANCELLED` 超时退款流程）
   - 改了对象的状态集合（`OrderStatus`、`DisputeDecision`…）
   - 改了 `contracts.py`、`sql/001_core.sql`、事件类型或 payload（R15：需两位开发者同意）
   - 改了某条规则的执行位置
4. 每次合并前跑兼容门禁：`scripts/check_compat.ps1`（Windows）或 `scripts/check_compat.sh`（3.11 + 3.13 + ruff）。
5. 不确定某个改动是否破坏规则 → 看第 4 节的「验证方式」列，跑对应测试。

---

## 1. 记法速查（与图例一致）

| 记号 | DOT 写法 | 含义 |
|---|---|---|
| 矩形（绿） | `shape=box color="#2E7D32"` | 对象（信息性） |
| 双边框 | `peripheries=2` | 物理对象（人、笔记本） |
| 虚线边框 | `style=dashed` | 环境对象（系统外：Render、Claude API、评委、行情源） |
| 椭圆（蓝） | `shape=ellipse color="#1565C0"` | 过程 |
| 对象内圆角框（棕） | HTML 嵌套表 `STYLE="rounded"` + `PORT` | 状态；边连到 `Object:port` 表示状态级链接 |
| 普通箭头 对象→过程 | 默认 | 消耗（consumption） |
| 普通箭头 过程→对象 | 默认 | 结果（result） |
| 双向箭头 | `dir=both` | 影响（effect：改变对象但不消耗） |
| 空心圆端 | `arrowhead=odot` | 工具（instrument，非人使能者——**AI agent 在 OPM 中是工具，不是 agent**） |
| 实心圆端 | `arrowhead=dot` | agent（人类使能者） |
| 标签 `c` | `label="c: ..."` | 条件链接：条件不满足则跳过该过程 |
| 粗蓝箭头 "invokes" | `style=bold arrowhead=vee` | 调用链接 |
| 黑三角 | `shape=triangle fillcolor=black` | 聚合-部分 |
| 双线白三角 | `shape=triangle peripheries=2` | 展示-特征（属性） |
| 灰虚线 "in-zoomed in SDn" | `lhead=cluster_SDn` | 细化：父过程在子 OPD 中展开 |
| 橙色 `[R2 R5]` | 过程标签第三行 | 该过程必须遵守的规则（见第 4 节） |

In-zoom 图中过程**自上而下 = 时间顺序**（用不可见边固定排序）。

---

## 2. OPL（Object-Process Language）— 与图一一对应

### SD — System Diagram
- **Trading Market Intelligence** requires Buyer Agent, Seller Agents, Clearing House and Price Oracle.
- **Trading Market Intelligence** requires Claude API, if `AL_LLM=1` (condition).
- **Trading Market Intelligence** affects Double-entry Ledger.
- **Trading Market Intelligence** yields Verified Market Intelligence and Event Log.
- **Producing Analytics** requires Event Log and yields Analytics Warehouse & KPIs.
- Dev Team handles **Developing & Deploying**, which yields Running Web App.
- Running Web App is an instrument of **Trading Market Intelligence** and **Producing Analytics**.
- Hackathon Jury & SAP Interviewer (environmental) is the beneficiary; it reviews KPIs and outcomes.
- Trading Market Intelligence zooms into SD1; Producing Analytics zooms into SD3; Developing & Deploying zooms into SD4.

### SD1 — Trading Market Intelligence (in-zoomed)
- Seller Agent exhibits Reputation. Buyer Wallet exhibits Spend Mandate.
- **Publishing Agent Cards** requires Seller Agent and yields Agent Card.
- **Registering** requires Agent Card, yields Registry and Reputation (initial 0.5).
- **Funding Buyer** yields Money at state *in buyer wallet* (once per buyer).
- **Assessing Tier** requires Buyer Agent and Buyer Wallet, and yields Survival Tier at one of *normal, low_compute, critical, dead*.
- **Discovering & Ranking** occurs if Survival Tier is not *dead*; requires Registry and Reputation; yields Ranked Cards.
- **Quoting (HTTP 402)** requires the top Ranked Card; yields Quote at *issued* and Acceptance Criteria.
- **Holding in Escrow** occurs if Quote is *issued* (not *expired*) and the amount is within Spend Mandate; changes Money from *in buyer wallet* to *in escrow*; yields Order at *FUNDS_HELD* and Payment Receipt.
- **Delivering (paid)** occurs if Payment Receipt is valid; changes Quote from *issued* to *redeemed*; yields Deliverable, including `content_hash` and the seller HMAC `content_signature` (`receipts.sign_content`; per-seller key derived from the shared secret).
- **Recording Delivery** changes Order from *FUNDS_HELD* to *DELIVERED* only after `receipts.verify_content` accepts the seller HMAC (R4, R7). A missing or bad signature is rejected and the order stays *FUNDS_HELD*. The buyer forwards the seller's hash and signature; it does not report an unverified hash of its own.
- **Expiring** occurs if Order is *FUNDS_HELD* and undelivered longer than the order TTL; changes Money from *in escrow* back to *in buyer wallet* (full refund, no fee) and Order to *CANCELLED*; affects Reputation (failed outcome); invokes **Emitting Events** (`payment.refunded` with status CANCELLED).
- **Verifying Contract** requires Deliverable, Acceptance Criteria and Price Oracle; yields Quality Report at *passed* or *failed*.
- **Settling** occurs if Quality Report is *passed*; changes Order from *DELIVERED* to *COMPLETED*; changes Money from *in escrow* to *with seller* and *platform fees*; affects Reputation (+).
- **Resolving Dispute** occurs if Quality Report is *failed*; changes Order from *DELIVERED* (detail in SD2).
- Holding in Escrow, Recording Delivery, Expiring, Settling and Resolving Dispute invoke **Emitting Events**, which yields Outbox Event.

### SD2 — Resolving Dispute (in-zoomed)
- **Opening** changes Order from *DELIVERED* to *DISPUTED*.
- **Checking Evidence Hash** yields Evidence at *hash matches* or *hash mismatch*.
- **Re-executing Acceptance** occurs if Evidence is *hash matches*; requires Acceptance Criteria (frozen at hold); yields Re-executed Quality Report.
- **Deciding** requires Re-executed Quality Report (or Evidence at *hash mismatch* → RELEASE); yields Decision at *RELEASE*, *REFUND_PARTIAL* or *REFUND_FULL*.
- **Refunding** occurs if Decision is *REFUND_PARTIAL* or *REFUND_FULL*; consumes Escrowed Money; changes Order from *DISPUTED* to *PARTIALLY_REFUNDED* or *REFUNDED*.
- **Releasing** occurs if Decision is *RELEASE*; consumes Escrowed Money; changes Order from *DISPUTED* to *COMPLETED*.
- Refunding and Releasing invoke **Updating Reputation**, which affects Seller Reputation.
- **Re-executing Acceptance** also yields Policy Band (allowed decision + refund % range, `disputes.policy_band`).
- **Guardian Investigating** occurs if AL_AGENT_MODE resolves to llm; requires LLM (guardian brain), Re-executed
  Quality Report and Policy Band; yields Ruling Proposal (decision, refund %, cited checks). Unfolded in SD5.
- **Deciding** requires Policy Band and, if it is inside the band and cites failed checks, Ruling Proposal;
  otherwise it uses the band default (`disputes.validate`).
- **Recording** yields Dispute Record (rationale + guardian text + ruling source).
- *The LLM reaches Deciding only through `disputes.validate`; nothing from the LLM reaches Refunding or Releasing* (R1).

### SD3 — Producing Analytics (in-zoomed)
- **Ingesting Events** requires Outbox (rows with seq > cursor); affects Ingest Cursor; yields Raw Events; invokes **Logging Run**.
- **Building dim_agents** and **Building fact_orders** require Raw Events and yield dim_agents and fact_orders.
- dim_agents and fact_orders feed KPI Views (`v_customer_360`, `v_agent_performance`, `v_daily_kpis`, `v_customer_rfm`).
- **Checking Data Quality** requires fact_orders and Core OLTP tables (reconciliation); yields DQ Result at *PASS* or *FAIL* (x9).
- **Serving API** requires KPI Views and DQ Result; yields API JSON.
- Viewer handles **Rendering Dashboard**, which requires API JSON and yields React Pages.

### SD5 — Agent Reasoning (unfolded; used by Buyer Agent in SD1 and Guardian in SD2)
- **Planning** requires Goal and LLM Provider; yields Message History and Agent Run Report at *running*.
- **Acting** requires LLM Provider; affects Message History; invokes **Calling Tool** once per tool_call and
  **Metering** once per LLM call.
- **Calling Tool** requires Tool Set and occurs if the Tool-side Policy Gate allows the call (rejections come back
  to the model as text).
- **Metering** affects Token Meter and invokes **Checking Budget**, which yields Budget at *within* or *exhausted*.
- **Reflecting** occurs when the model stops calling tools or Budget is *exhausted*; changes Agent Run Report from
  *running* to *completed* (or *budget_stopped* / *failed*).
- **Grounding** affects Agent Run Report: order ids not produced by tool results are removed.
- **Auto-finalizing** requires the Policy Gate: deliveries the model left undecided are verified, then accepted
  or disputed by policy.
- **Persisting Telemetry** requires Agent Run Report at *completed*; yields llm.usage and agent.run.finished events
  (one transaction with the trace) that feed SD3.

### SD4 — Developing & Deploying (in-zoomed)
- Codebase consists of Frozen Contract, Economy part (A) and Market & Analytics part (B).
- Dev A and Dev B handle **Freezing Contract**, which yields Frozen Contract.
- Dev A handles **Implementing A**; Dev B handles **Implementing B**; both require Frozen Contract.
- **Checking Compatibility** requires both parts; yields Compat Gate at *green on 3.11 AND 3.13* or *red* (red → fix).
- **Merging** occurs if Compat Gate is *green*; yields GitHub main branch.
- **Building Image** yields Container Image; **Deploying** yields Render Web Service at *asleep*.
- **Warming Up** changes Render Web Service from *asleep* to *awake*.
- Presenter handles **Presenting Demo**, which occurs if Render Web Service is *awake*.

---

## 3. 事物 → 代码映射（接手时的导航表）

| OPM 事物 | 类型 | 代码 | 负责人 |
|---|---|---|---|
| Agent Card / Quote / Receipt / Deliverable / Quality Report / Decision | 对象 | `src/agentledger/contracts.py` | A+B（冻结） |
| Order（7 状态） | 对象 | `contracts.OrderStatus`, `core.orders`, `economy/escrow.py` | A |
| Money / Ledger | 对象 | `economy/ledger.py`, `core.ledger_entries` | A |
| Registry / Reputation | 对象 | `economy/registry.py`, `core.agents` | A |
| Survival Tier / Buyer Agent | 对象 | `agents/buyer.py` | A |
| Seller Agents | 对象 | `sellers/catalog.py`（B），`sellers/app.py`（A：402 paywall） | A/B |
| Price Oracle | 环境对象 | `market/data.py` | B |
| Acceptance Criteria / Verifying | 对象/过程 | `market/quality.py`, `market/backtest.py` | B |
| Signals (sellers' models) | — | `market/signals.py`, `market/features.py` | B |
| Holding / Delivering / Recording Delivery / Settling | 过程 | `escrow.hold`, `escrow.mark_delivered`（`receipts.verify_content`）, `escrow.settle`, `platform_api.py` | A |
| Expiring | 过程 | `escrow.expire_undelivered` | A |
| Resolving Dispute (SD2) | 过程 | `economy/disputes.py`（policy_band / validate） | A |
| Guardian Investigating (SD2) | 过程 | `agents/guardian.py` | A |
| Buyer Agent brain (SD1 → SD5) | 对象 | `agents/buyer_agent.py`（7 个工具 + 工具侧策略） | A |
| Planning / Acting / Reflecting (SD5) | 过程 | `agents/graph.py`（LangGraph） | A |
| LLM Provider (SD5) | 环境对象 | `agents/llm.py`（Mistral 默认 / Claude / OpenAI-compatible） | A |
| Token Meter / Budget / Agent Run Report (SD5) | 对象 | `agents/accounting.py`, `agents/telemetry.py`, `sql/003_agents.sql` | A |
| Building AI cost facts (SD3) | 过程 | `sql/marts/fact_llm_calls.sql`, 视图 `v_ai_cost_by_agent/model` | B |
| Agent Console 页面 | — | `frontend/src/pages/AgentConsole.jsx`（规则 §11） | 前端负责人 |
| Emitting Events | 过程 | `db.emit_event` | A |
| Market round orchestration | 过程 | `runner.py`（CLI `demo.py`，Web `server.py /api/round`） | A |
| Ingesting / Building / DQ / Logging | 过程 | `analytics/ingest.py`, `analytics/pipeline.py`, `sql/marts/*`, `sql/quality_checks.sql` | B |
| KPI Views | 对象 | `sql/002_analytics.sql` | B |
| Serving API | 过程 | `server.py` | A |
| Rendering Dashboard | 过程 | `frontend/`（规则：`docs/FRONTEND_RULES.md`） | 前端负责人 |
| Compat Gate | 对象 | `scripts/check_compat.*`, `.github/workflows/ci.yml` | A+B |
| Container Image / Render | 对象 | `Dockerfile`, `render.yaml` | A |

---

## 4. 规则（不变量）→ 执行位置 → 验证方式

| ID | 规则 | 执行位置 | 验证方式 |
|---|---|---|---|
| R1 | LLM agent 选择动作、提出裁决；每一笔资金变动由确定性工具/策略授权；裁决只在 policy band 内生效 | `buyer_agent` 工具侧检查、`disputes.validate`、`escrow.*` | `tests/test_agents.py`（越界裁决回退规则表）；`economy/` 不得 import `agents` |
| R2 | 金额为整数分；每笔账务借贷和为 0；只有 treasury 可为负 | `ledger.post` | `tests/test_economy.py`；DQ `ledger_txns_balanced`、`no_negative_agent_balance` |
| R3 | 状态变更与 outbox 事件同一事务 | `db.transaction`（BEGIN IMMEDIATE）+ `emit_event` | DQ `ingestion_complete`、`oltp_vs_warehouse_order_count` |
| R4 | 订单状态只能经 `_transition` 比较并设置 | `escrow._transition` | `test_settle_pays_seller_minus_fee_and_cannot_repeat` |
| R5 | 幂等：同 key 重复 hold 返回同一订单；买家只充值一次；收据只兑现一次 | `escrow.hold`、`registry.register_buyer`、`sellers/app.py redeemed` | `test_hold_is_idempotent_and_receipt_verifies` |
| R6 | 先检查授权额度（单笔/日限额），再扣款；生存等级限制价格 | `escrow.hold`、`buyer.TIERS` | `test_insufficient_funds_and_mandate_are_enforced` |
| R7 | 卖方执行**报价时**的任务；验证支付 HMAC、金额、报价归属，并用派生密钥 HMAC 签交付 `content_hash`（平台在 Recording Delivery 用 `verify_content` 验签后才 `_transition`，见第 2 节，R4） | `sellers/app.py::task`, `receipts.sign_content` | e2e；手工：篡改 `X-Payment` 应得 402 |
| R8 | 仲裁者重算证据哈希、重跑验收 | `disputes.open_and_resolve` | e2e 中 hype 卖方被全额退款 |
| R9 | 全过→RELEASE；关键项失败→全额退款；仅表现项失败→50% 退款 | `disputes.decide` | e2e 状态集合含 REFUNDED/PARTIALLY_REFUNDED |
| R10 | 时点一致：行日期 ≤ as_of；合成价格固定长度；种子用 crc32 | `market/data.py`、`quality.py` | `test_synthetic_prices_are_point_in_time_stable` |
| R11 | 数仓只由事件构建；event_id 去重；集市可重复重建 | `ingest.py`、`sql/marts/*` | 连续跑两次 pipeline 结果相同 |
| R12 | 11 项 DQ 全部 0 违规（含 AI 成本：调用合计 = 运行合计）；托管余额 = 未结订单金额 | `sql/quality_checks.sql`、`/platform/ledger/check` | `tests/test_e2e.py` |
| R13 | 3.11 与 3.13 双绿才可合并 | `scripts/check_compat.*`、CI 矩阵 | 运行脚本 |
| R14 | 前端只经 `api.js` 调后端；金额 `fmt.usd`；状态=颜色+图标+文字 | `frontend/src/api.js` | `docs/FRONTEND_RULES.md` 第 10 节 |
| R15 | `contracts.py`、`sql/001_core.sql` 冻结，改动需双方同意并更新 OPM | 流程约束 | PR 审查 |
| R16 | 私有提纲文档不出本机；不声称与 SAP 产品集成 | `.gitignore`、`.dockerignore` | `git status` 中不得出现该文件 |
| R17 | 每次 LLM 调用都计量（token、整数 micro-USD、价格来源）；工具次数/费用到预算即停；轨迹与事件同一事务落库 | `agents/accounting.py`、`agents/telemetry.py` | `test_llm_buyer_agent_runs_the_protocol_and_meters_every_call`；DQ `ai_cost_reconciles_calls_vs_runs` |
| R18 | Grounding：报告只能引用工具结果中的订单；guardian 必须引用确实失败的检查；未决交付由策略收尾 | `run_llm_buyer`、`disputes.validate`、`finalize_open_orders` | `test_agents.py`（幻觉 order id 被丢弃；越界/错误引用被拒） |

---

## 5. 已知缺口（接手可直接领取）

| 缺口 | OPM 位置 | 建议实现 |
|---|---|---|
| 价格协商（最多 3 轮） | SD1 Quoting 与 Holding 之间 | 新过程 *Negotiating*：LLM 可提议还价，策略决定（R1） |
| 真实支付通道 | SD Money | 在 `ledger.post` 外加 `PaymentRail` 接口（Stripe test / x402 testnet） |
| Kafka / Airflow | SD3 Ingesting / pipeline | `ingest.py` 换 Kafka consumer；`pipeline.TASKS` 1:1 映射成 Airflow DAG |

新增任何一项时：先在 DOT 中加过程/状态与 `[R…]` 标签，再写代码，再补第 2–4 节。
