# SmartHR-Agent

> 面向招聘业务闭环的 AI Agent 工程化实践。
> 一个人机协同、可解释、可追溯的**候选人研判 Agent**,从简历、筛选、面试、Offer 到入职,AI 深度参与并给出分析与建议——但录用、淘汰、发 Offer 这些决定,始终由人做出。

招聘数据散落在简历、初筛、面试、Offer、入职等多个环节,AI 的结论又常常难以验证。这个项目把 AI 接进一条真实的招聘流程,目标很明确:**让 AI 基于完整的证据链去做分析和判断,同时保证结论可溯源、过程可回放、质量可评测、失败可降级**。它不是一个调 API 的 Demo,而是一个可以部署、可以解释、可以持续验证的 Agent 工程。

---

## ✨ 核心设计:从零构建的工具调用 Agent

这个项目的核心是一个**不依赖任何 Agent 框架、从零手写的工具调用循环**(`candidate_agent_runtime.py`),它用一套约 200 行的循环实现了完整的 ReAct 式工具调用 Agent:

```
system 提示(决策规则) → user(任务 + 可用数据源)
      │
      ▼
  LLM 选择工具 ──▶ 执行工具 ──▶ 结果回填对话 ──▶ 判断是否收敛
      │                                             │
      │ 未收敛,继续                               收敛
      ▼                                             ▼
  (最多 6 步 / 超时 / 达到上限)           调用 submit_answer / submit_report 一次性提交最终结果
```

- 基于 OpenAI 兼容的 **function calling**,`tool_choice: "auto"` 让模型自主决定调用哪个工具、调用几次、传什么参数。
- **不在代码里写死 if-else 挑工具**。工具的选择权交给模型,代码只负责执行、兜底和记账;而"怎样做对的决策"则通过**工具描述 + 系统提示词**来引导(优先取必要数据、同一数据源取最新、证据够了就提交、工具出错不得编造)。
- 循环自带三道兜底:工具名未知 / 参数不符合 schema → 以 `tool` 消息把错误回传给模型,让它自纠;❌ 空转 → 追加"请继续"引导;❌ 达到步数上限 `MAX_TOOL_STEPS=6` 或超时 → 抛出异常并**自动降级人工**。
- 同一套循环服务两个场景:`goal="answer"`(实时问答)与 `goal="report"`(生成研判报告)。

> 为什么不用框架?Agent 框架把"模型如何决策"这段逻辑封装成了黑盒,而你很难对每一步负责、解释和度量。手写循环换来的是**对每一步的完全控制**——能解释模型为什么这么选,能记录每一次调用,也能在出错时精确地兜底。

---

## 其他亮点

### 轨迹级可观测:决策过程可完整回放
- 工具轨迹 `tool_trajectory`:每次工具调用的名称、步数、耗时、请求参数快照、结果快照、错误信息全部落库。
- AI 调用日志 `AiCallLog`(关联到 `ai_call_log_ids`):每次 LLM 调用的模型、Prompt 版本、Token、耗时、重试次数与状态。
- 前端「研判报告 → 分析过程」会直接展开整个轨迹——Agent 每一步做了什么,一目了然。

### 多源证据聚合 + 可溯源引用
Agent 通过工具按需拉取候选人的**全生命周期证据**:简历资料、AI 初筛、人工决策、面试评价、面试报告、Offer、入职状态;并用 `search_enterprise_knowledge` 检索企业招聘知识库(制度、岗位标准、面试、Offer 规范)。回答中的每条事实与知识引用都带来源,可一路追溯到原始证据或具体文档。

### 负责任的 AI 边界:机器建议,人类拍板
- 候选问答与分析**只提供服务范围内的判断**,不自动录用 / 淘汰 / 发送 Offer / 改动候选人阶段——综合建议是信息性的,供招聘专员参考。
- Agent 失败(上游不可用、超时、超步)时自动降级为人工处理(`manual_fallback`),上下文快照已保存,业务不中断。

### Agent 工程化支撑体系
| 能力 | 说明 |
|---|---|
| **PromptOps** | 场景化 Prompt 模板,可发布版本、回滚、审计;Agent 使用的每条 Prompt 都关联 `prompt_version` |
| **RAG** | 企业知识库文档上传 → 分块 → 异步 Embedding → pgvector 检索,引用带相关性分数与来源;已接入简历评分、面试报告与候选问答 |
| **离线评测 + 错误案例库** | 用固定合成样本跑真实的解析、评分、分组与证据逻辑,沉淀误判、证据不足、格式错误、幻觉等案例 |
| **AI 可观测性** | 任务中心 + 调用日志,记录场景 / 模型 / Token / 耗时 / 失败原因 / 重试轨迹 |

---

## 🧱 技术栈

| 层 | 技术 |
|---|---|
| 后端 | FastAPI · SQLAlchemy 2.0 · Alembic · Pydantic v2 · Celery · Redis |
| 数据 | PostgreSQL 16 + **pgvector**(语义检索) |
| AI | 自封装 OpenAI 兼容客户端(httpx,统一重试 / 超时 / 并发限流 / Token 计量)· 自研 Agent 运行时 |
| 前端 | React 19 · TypeScript · Vite · Ant Design 5 · TanStack Query 5 |
| 工程 | Docker Compose · Alembic 迁移 · Ruff · Pytest · Vitest |

---

## 📦 功能概览

### Agent 层(核心)
- **候选人问答 Agent**:围绕候选人汇聚简历、初筛、人工决策、面试、Offer、入职与企业知识库证据,做可解释、可追溯的实时问答;失败自动降级人工。
- **候选人研判报告**:生成结构化研判(匹配度、亮点、风险、矛盾点、证据缺口、下一步建议、待核实问题、综合建议 + 证据 / 知识引用 + 工具轨迹),支持幂等生成。

### 招聘业务闭环
招聘需求 → 职位与版本化筛选标准 → 简历批次上传 / 解析 / OCR / 脱敏 → AI 初筛(硬条件、分维度评分、证据引用、人工改判)→ 候选人对比与档案修正 → 候选人流程看板 → 面试计划 / 安排 / 评价 / 报告 → 薪酬与 Offer 审批、候选人 Offer 门户 → 入职跟踪;外加候选人中心、重复检测、人才库与推荐、工作台、数据分析、站内消息、沟通模板与留痕。

### 工程与安全
四类可叠加角色(管理员 / 招聘专员 / 用人经理 / 审批人),HttpOnly Cookie 会话(Redis),支持强制改密、停用即会话失效、权限变更会话失效;简历解析异步隔离、失败补偿与批次二次确认永久删除;登录、原件访问、标准确认等关键操作全程审计。

---

## 🚀 快速开始(Docker)

```powershell
# 1. 配置环境
Copy-Item .env.example .env
# 编辑 .env:设置 APP_SECRET_KEY、初始账号,以及你的 AI / Embedding 模型配置

# 2. 一键构建启动(含 PostgreSQL/pgvector、Redis、API、Worker、Web)
docker compose up -d --build

# 3. 访问
#    Web:   http://localhost:8080
#    健康:  http://localhost:8080/api/health/ready
```

写入演示数据(可选,便于直接体验):

```powershell
docker compose exec api python -m app.demo.seed
# 登录: demo-admin / Demo@123456(另有 demo-recruiter / demo-manager / demo-approver)
```

停止:`docker compose down`(默认保留数据卷;加 `-v` 才清数据)。

---

## 🔧 关键配置

### 对话模型(AI Agent 的"大脑",OpenAI 兼容)
```text
AI_BASE_URL / AI_API_KEY / AI_MODEL / AI_TIMEOUT_SECONDS / AI_MAX_CONCURRENCY
```

### 嵌入模型(知识库 RAG / 语义检索,OpenAI 兼容)
```text
EMBEDDING_ENABLED=true
EMBEDDING_BASE_URL / EMBEDDING_API_KEY / EMBEDDING_MODEL / EMBEDDING_DIMENSION
EMBEDDING_VERSION / EMBEDDING_TIMEOUT_SECONDS / EMBEDDING_BATCH_SIZE / EMBEDDING_MAX_CONCURRENCY
```

> Embedding 默认关闭;开启后新增知识文档、候选人档案会自动异步建索引,支持幂等跳过、失败隔离、受控重试、强制重建与模型版本并存。

### 认证初始化
API 启动时自动迁移,并在账号不存在时初始化唯一招聘专员:
```text
INITIAL_RECRUITER_USERNAME / INITIAL_RECRUITER_PASSWORD / INITIAL_RECRUITER_DISPLAY_NAME
```

---

## 📁 目录结构

```text
backend/
  app/
    api/routes/              各业务域 API(candidates、interviews、offers、knowledge、ai_observability…)
    services/
      candidate_agent_runtime.py   ★ 自研 Agent 工具调用循环
      candidate_agent_tools.py     ★ Agent 工具定义与调度器
      candidate_agent_context.py   ★ 候选人全生命周期证据上下文快照
      ai_client.py                 OpenAI 兼容客户端(重试 / 超时 / 并发 / Token 计量 / 工具调用)
      embedding_client.py          嵌入客户端
      prompt_templates.py          PromptOps(模板 / 版本 / 发布 / 回滚)
      recruitment_knowledge.py     企业知识库 RAG(分块 / 索引 / 检索 / 引用)
      ai_observability.py          AI 调用日志 / 任务中心
    models/                    SQLAlchemy 模型(含 candidate_agent_report 等)
    demo/seed.py               幂等演示数据种子
    evaluation/                 固定合成样本离线评测
  migrations/                  Alembic 迁移
frontend/
  src/
    pages/CandidateAgentPage.tsx   候选问答 + 研判报告前端
    components/AppLayout.tsx       布局 / 导航 / 账号菜单
docs/                        项目文档与学习记录
docker-compose.yml
```

---

## ✅ 质量与测试

```powershell
# 后端
python -m ruff check backend
python -m pytest backend

# 前端
Set-Location frontend
npm run lint
npm run test
npm run build
```

关键路径均有测试覆盖:AI 客户端工具调用解析、Agent 运行时循环、工具调度器、知识库检索、导航与账号菜单,以及各业务域前端流程。

---

## 🏗️ 演示数据

`python -m app.demo.seed` 幂等生成:4 个演示账号、1 个 DEMO 岗位、4 位覆盖不同阶段(AI 初筛 / 人工决策 / 流程 / 面试 / Offer / 入职)的候选人、AI 任务与调用日志、企业知识库文档与 AI 评测样本——方便一键体验完整业务闭环与 Agent 研判。
