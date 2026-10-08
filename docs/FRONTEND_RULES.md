# 前端框架与规则（Frontend Rules）

> 前端页面按本规则实现（React + Vite；shell、API 客户端、i18n、设计 token 已就绪）。任何人（包括 AI agent）都可以直接实现或修改页面，只要遵守下面的规则。
> 参考实现：`D:\AI_Models\football match prediction\frontend`（EuroGoal），技术栈与模式保持一致。

## 1. 技术栈（与 EuroGoal 相同，不新增依赖）

| 项 | 选择 | 说明 |
|---|---|---|
| 框架 | React 19 + Vite 5 | `npm run dev / build / lint` |
| 图标 | lucide-react | 唯一 UI 依赖 |
| 路由 | **不用 router** | `App.jsx` 的 `VIEWS` 数组 + `useState` 切换，加页面 = 加一项 |
| 图表 | **不引图表库** | 柱状图用 CSS 宽度百分比（EuroGoal `PredictionGauge` 的做法），够用且零风险 |
| 样式 | 单个 `src/index.css` | 顶部是 token 和 shell，组件样式按块追加在末尾 |
| i18n | 自研 `i18n.jsx` | 同 EuroGoal 机制，但**英文是 key、默认英文**（评委讲英文，缺翻译时回退英文） |

新增任何 npm 依赖前先在群里说。

## 2. 目录与职责

```text
frontend/
├── index.html            # 只放 meta/title，不写逻辑
├── vite.config.js        # dev 代理 /api /platform /sellers -> :8000
└── src/
    ├── main.jsx          # 挂载 + LanguageProvider（不要改）
    ├── App.jsx           # shell：header、tab、语言切换（只在这里加/删页面）
    ├── api.js            # 唯一调用后端的地方 + 金额/百分比格式化 fmt
    ├── agentRound.jsx    # 全局共享的后台交易回合（交易大厅 + 智能体控制台共用，一次只跑一轮）
    ├── i18n.jsx          # useT() -> { t, lang, setLang }
    ├── translations.js   # ZH 表：key = 英文原文
    ├── index.css         # token + shell + 组件样式块
    ├── pages/            # 一个视图一个文件；文件头注释 = 该页需求说明（先读）
    │   ├── Market.jsx        # 演示主屏：KPI + 运行一轮 + 结果表
    │   ├── Agents.jsx        # 卖方信誉/可靠性
    │   ├── Customer360.jsx   # 买方 360 + RFM
    │   └── DataQuality.jsx   # DQ 检查 + 管道 + 事件流
    └── components/       # 可复用组件：一个组件一个文件，PascalCase，默认导出
```

## 3. API 契约（后端 `src/agentledger/server.py`，改动必须两边同步）

| 调用 | 方法/路径 | 返回 |
|---|---|---|
| `api.health()` | GET `/api/health` | `{status, sellers, agent_mode, llm_provider, llm_model, price_per_m_tokens, budget}` |
| `api.summary()` | GET `/api/summary` | `{kpi, agents[], customers[], rfm[], dq[], orders[], ai_costs[], ai_models[]}` |
| `api.events(n)` | GET `/api/events?limit=n` | `[{seq, event_type, aggregate_id, occurred_at, payload_json}]` |
| `api.runRound(symbols, rounds)` | POST `/api/round` | `{purchases[], agent_run, pipeline[], reconciliation}`；LLM 模式下可能要 30–90 秒 |
| `api.startAgentRound(symbols)` | POST `/api/agent/rounds` | `{job_id}`，立即返回，后台运行 |
| `api.agentRound(jobId)` | GET `/api/agent/rounds/{job_id}` | `{status, mode, run, purchases, result, error}`，运行中每 1.5 秒轮询 |
| `api.agentRuns(n)` | GET `/api/agent/runs` | 历史运行（只有汇总） |
| `api.agentRun(runId)` | GET `/api/agent/runs/{run_id}` | 完整轨迹 `steps[]` + 子运行 `children[]`（guardian） |
| `api.resetDemo(token)` | POST `/api/demo/reset` | 清空订单/账本/智能体运行/AI 费用并重新充值买方钱包；`health.reset_requires_token` 为真时需 `X-Admin-Token`；有回合在跑时返回 409 |
| `api.agentCards()` | GET `/sellers/.well-known/agents.json` | 卖方 agent card 列表 |

字段规则：
- **所有金额是整数分（`*_minor`）**，只能用 `fmt.usd()` 显示，前端不做浮点金额运算。
- 比率（`success_rate`、`dispute_rate`、`hit_rate`）是 0–1 小数，用 `fmt.pct()` / `fmt.num()`。
- `kpi`：`orders, settled_gmv_minor, dispute_rate, fees_minor, buyer_balance_minor`。
- `purchases[]`：`symbol, seller, price_minor, status, order_id, latency_ms, hit_rate, refund_minor, rationale, notes[]`。
- `status` 取值：`COMPLETED | REFUND_PARTIAL | REFUND_FULL | RELEASE | SKIPPED | PAYMENT_REJECTED | SELLER_ERROR`；
  订单 `final_status`：`COMPLETED | PARTIALLY_REFUNDED | REFUNDED | ...`（见 `contracts.py`）。
- 错误统一是 HTTP 非 2xx + `{"detail": "..."}`，`api.js` 已转成 `Error(detail)`。

## 4. 视觉与数据可视化规则

1. **只用 token**（`index.css` 顶部的 CSS 变量），组件里不写裸 hex。深色/浅色由 `prefers-color-scheme` 自动切换。
2. **单系列图表只用 `--primary` 一个颜色**（例如信誉柱状图），不按排名换色，不用彩虹色。
3. **状态色只表达结果**：`--status-good / warn / bad`，且必须**图标 + 文字标签**一起出现（✓ PASS / ✗ FAIL、Completed / Partial refund / Full refund），不能只靠颜色。
4. 不做双 Y 轴；不在每个数据点上标数字（只在柱末标一个值）。
5. 悬停提示用 `title` 属性或简单 tooltip；表格数字右对齐 + `font-variant-numeric: tabular-nums`。
6. 文字用 `--text-*`，不要用系列色写文字。
7. 移动端 ≤640px 单列；表格外包 `overflow-x: auto`，页面不能横向滚动。

## 5. 状态处理（每个页面都要有）

- **loading**：按钮禁用 + “Agents are trading…” 之类的进行时文案。
- **empty**：还没跑过一轮时显示 “Press Run market round” 引导，而不是空表。
- **error**：显示 `error.message` + Retry 按钮。
- **Render 冷启动**：免费实例休眠后首个请求约 50 秒。首次 `api.health()` 失败时显示 “Waking up the server…” 并每 5 秒重试，最多 2 分钟。

## 6. i18n 规则

- JSX 里所有可见文字都包 `t('English text')`；中文写在 `translations.js` 的 `ZH`。
- 数据值（agent id、股票代码、金额）不翻译。
- 默认语言 `en`；语言选择存 `localStorage`（只存这个，业务数据不存浏览器）。

## 7. 页面与演示脚本的对应

1. **Market**（主屏）：点 “Run market round” → 结果表依次出现：`sig-hype` 被全额退款（stale）→ `sig-rsi` 部分退款 → `sig-momentum` 成交 → 对账 ✓。连点 2–3 次，信誉变化在 **Agents** 页可见。
2. **Agents**：信誉柱状图 + 可靠性表（讲 “IT/云运维分析”：成功率、延迟、争议率）。
3. **Customer 360**：买方画像 + RFM 分群（讲 SAP CPIT Customer 360）。
4. **Data quality**：9 项检查全 PASS + 管道血缘 + outbox 事件流（讲数据治理、对账、可重放）。

## 8. 开发与部署

```bash
# 后端（仓库根目录）
uvicorn agentledger.server:create_app --factory --port 8000
# 前端
cd frontend && npm install && npm run dev        # http://localhost:5173，自动代理到 :8000
npm run lint && npm run build                    # 提交前必须通过
```

- 第一次 `npm install` 后**提交 `package-lock.json`**，然后把 Dockerfile 里的 `npm install` 改成 `npm ci`。
- 线上：Render Blueprint（`render.yaml`，runtime docker）。Dockerfile 先 build 前端，FastAPI 在 `/` 挂载 `frontend/dist`，同源，无需 CORS。

## 9. 禁止事项

- 不在 `api.js` 以外调用 `fetch`；不在前端硬编码后端地址（同源相对路径）。
- 不对金额做浮点运算；不在前端放任何密钥。
- UI 文案不得暗示真实资金、真实交易建议或与任何 SAP 产品的集成（模拟资金，演示用途）。
- 不改 `main.jsx`、`i18n.jsx` 的机制；不引入 router / UI 组件库 / 图表库 / CSS 框架。

## 10. 前端完成标准（DoD）

- [ ] 4 个页面都有 loading / empty / error 三态
- [ ] Market 页能完整跑演示脚本，对账结果可见
- [ ] 中英切换无遗漏（中文模式下无英文残留的可见文案，数据值除外）
- [ ] 640px 宽度下无横向滚动
- [ ] `npm run lint`、`npm run build` 通过；Docker 镜像本地 `docker build .` 通过

## 11. AI 智能体页面（Agent Console）与 Token 费用显示

组织方要求：必须是**真正干活的 AI agent**，并且**显示 token 消耗产生的费用**。后端已实现（LangGraph：plan → react 工具循环 → reflect；买方 agent + 仲裁 guardian agent），前端负责把它“演”出来。页面：`pages/AgentConsole.jsx`。

**数据结构**
- `run`（AgentRunReport）：`run_id, agent_id, role (buyer|guardian), status (running|completed|budget_stopped|failed), provider, model, llm_calls, tool_calls, input_tokens, output_tokens, cost_micro_usd, summary, steps[], children[]`。
- `step`：`seq, kind (plan|llm|tool|policy|error), name, detail, input_tokens, output_tokens, cost_micro_usd, latency_ms, at`。
  - `kind=llm`：`detail.text`（模型文字）、`detail.tool_calls`（本步请求的工具名）。
  - `kind=tool`：`detail.args`、`detail.result`（已截断到 1500 字符）、`detail.ok`。
  - `kind=policy`：预算停止、grounding 丢弃、自动收尾、guardian 回退 —— **必须高亮**，这是“确定性策略管住 LLM”的证据。

**费用显示规则**
1. LLM 费用单位是**整数 micro-USD**，只能用 `fmt.microUsd()` 显示（小于 1 分时显示 4 位小数）；token 数用 `fmt.tokens()`。
2. 每个 llm 步骤显示：输入/输出 token、费用、延迟；运行总计实时累加（轮询时更新），并和预算（`health.budget.max_cost_usd`）并排显示进度。
3. 价格来源必须可见：`health.price_per_m_tokens.source`（Mistral 部分价格来自第三方跟踪站，页面要写“估算”）。
4. 完成后显示单位经济：`AI spend $x for N orders = $y per order`，以及数据采购花费（cents）对比 AI 花费（micro-USD）——两种单位不要混算，分别格式化。
5. Market 页 KPI 行增加两格：`AI spend`（`kpi.ai_cost_micro_usd`）、`LLM calls`（`kpi.llm_calls`）。Agents 页可加“AI 成本按 agent / 按模型”表（`ai_costs[]`、`ai_models[]`）。
6. `agent_mode === 'rule'` 时页面明确写“规则模式（未配置 API key）”，不要假装是 LLM。

**轮询**：`startAgentRound` 拿到 `job_id` 后每 1.5 秒调 `agentRound`；`status !== 'running'` 即停止；页面卸载时清理定时器；同一时间只允许一个 job。

**演示脚本（Agent Console）**：点运行 → 观众看到 plan → 工具调用逐条出现（check_wallet → search_sellers → request_quote → buy → verify_delivery → open_dispute）→ guardian 子运行展开（6 个调查工具并行 → submit_ruling 被策略校验）→ 换卖家成交 → 最终报告 + 费用合计（一轮约 $0.08–0.10，Mistral Medium 估价）。
