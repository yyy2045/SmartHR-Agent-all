# SmartHR-Agent-all

SmartHR-Agent 是一个围绕招聘业务闭环落地的 AI Agent 工程化项目。招聘流程是业务载体，项目重点展示 AI 如何接入真实流程、如何可解释与可追溯、如何结合异步任务、Embedding、RAG、Prompt 版本管理和离线评测，并始终由人类做最终招聘决策。

## AI 工程化专项

- AI 调用日志与任务中心：记录场景、模型、Prompt 版本、Token、耗时、状态、失败原因和重试轨迹。
- Prompt 模板管理与版本化：按 JD 生成、简历评分、面试报告和候选人 Agent 管理可发布、可回滚的模板。
- 企业招聘知识库 RAG：上传制度、岗位标准、面试评分、Offer 规则和沟通话术，检索结果带引用来源。
- 候选人问答 Agent：围绕候选人详情汇总简历、筛选、面试、Offer、入职和知识库证据，辅助招聘专员分析但不自动决策。
- AI 评测与错误案例库：使用固定合成样本比较模型和 Prompt 版本，沉淀误判、证据不足、格式错误和幻觉案例。

## 已完成招聘业务闭环

- 单招聘专员账号登录、HttpOnly Cookie 会话和前端路由保护。
- 管理员、招聘专员、用人经理、审批人四类可叠加角色，支持临时密码、强制改密、停用和权限变更会话失效。
- 招聘需求、审批、职位创建、岗位负责人分配和版本化筛选标准。
- 职位管理、人工筛选标准、AI JD 草稿和不可变标准版本。
- 单批最多 50 份 PDF、DOCX、JPG、PNG 简历上传与逐文件状态。
- PDF/DOCX 文本提取、扫描件和图片 OCR、失败隔离与重试。
- 创建简历批次时可选择将解析原文或本地脱敏文本发送给 AI，默认发送原文且创建后不可修改。
- 硬条件三态判断、自动淘汰、分维度评分、证据引用与人工改判。
- 最多 3 名同职位、同标准、同分析版本候选人横向对比。
- 候选人档案修正、单人重跑、整批重跑和历史版本保留。
- 登录、原文件访问、标准确认、自动淘汰恢复、人工决策和重跑审计。
- 批次二次确认永久删除、数据库级联清理和文件删除失败补偿。
- 基于 PostgreSQL 与 pgvector 的候选人语义分块、异步 Embedding、版本化索引和重建状态接口。
- 候选人中心、跨职位应聘记录、重复候选人提示、人才库与推荐。
- 面试计划、面试安排、结构化评价、面试报告、薪酬与 Offer 审批、候选人 Offer 门户、入职跟踪。
- 招聘工作台、数据分析、站内消息、沟通模板和沟通留痕。

## 本地启动

1. 创建本地环境配置：

   ```powershell
   Copy-Item .env.example .env
   ```

2. 修改 `.env` 中的示例密码、应用密钥和后续需要使用的模型配置。

3. 构建并启动服务：

   ```powershell
   docker compose up -d --build
   ```

4. 访问：

   - Web：http://localhost:8080
   - API 存活检查：http://localhost:8080/api/health/live
   - API 就绪检查：http://localhost:8080/api/health/ready

5. 查看容器状态：

   ```powershell
   docker compose ps
   ```

6. 停止服务：

   ```powershell
   docker compose down
   ```

`docker compose down` 不会删除数据库和 Redis 数据卷；只有显式增加 `-v` 才会删除数据。

## 后端登录认证

API 启动时会自动执行 Alembic 迁移，并在账号不存在时根据以下环境变量初始化唯一招聘专员：

```text
INITIAL_RECRUITER_USERNAME
INITIAL_RECRUITER_PASSWORD
INITIAL_RECRUITER_DISPLAY_NAME
```

初始密码使用 Argon2 哈希保存。修改环境变量不会覆盖已经存在的用户。

当前认证接口：

```text
POST /api/auth/login
GET  /api/auth/me
POST /api/auth/logout
```

登录会话使用 HttpOnly Cookie，服务端会话保存在 Redis。登录页、认证状态恢复和业务路由保护已经接入前端。除登录和健康检查外，业务接口均要求有效会话；职位筛选数据按招聘专员的职位归属校验，企业人才知识库基础接口由所有已认证招聘专员共享。

## AI 与异步任务配置

OpenAI 兼容服务通过以下环境变量配置：

```text
AI_BASE_URL
AI_API_KEY
AI_MODEL
AI_TIMEOUT_SECONDS
AI_MAX_CONCURRENCY
```

未配置真实模型时，职位和简历 AI 功能会返回可读错误，人工职位标准、历史数据和已有结果不受影响。

简历解析和分析由 Celery Worker 执行。默认并发为 2，可通过 `CELERY_WORKER_CONCURRENCY` 配置为 1 或 2；其他值会被拒绝。单批简历上限由 `MAX_BATCH_FILE_COUNT` 配置，最大值为 50。

## 企业人才知识库基础

PostgreSQL 容器使用带 pgvector 扩展的镜像。候选人结构化档案会按教育、工作、项目、技能、证书和语言等语义分块，并保留候选人档案版本、来源片段编号、Embedding 模型和索引版本。电话和邮箱仍保存在业务档案中供招聘专员查看，但进入 Embedding 前会被替换，不会发送给向量服务。

Embedding 默认关闭，只有完成以下 OpenAI 兼容服务配置并显式启用后，分析完成的候选人档案才会异步建立索引：

```text
EMBEDDING_ENABLED
EMBEDDING_BASE_URL
EMBEDDING_API_KEY
EMBEDDING_MODEL
EMBEDDING_DIMENSION
EMBEDDING_VERSION
EMBEDDING_TIMEOUT_SECONDS
EMBEDDING_BATCH_SIZE
EMBEDDING_MAX_CONCURRENCY
```

当前基础接口：

```text
GET  /api/knowledge/documents/{document_id}/index
POST /api/knowledge/documents/{document_id}/index/rebuild
```

索引任务支持幂等跳过、失败隔离、受控重试、强制重建和模型版本并存。删除简历批次或候选人档案时，关联向量分块会同步级联删除。当前候选人向量索引用于人才召回和后续 Agent 上下文检索，不替代硬条件判断和简历原文证据。企业招聘知识库 RAG 将作为独立 AI 专项继续建设，面向制度、岗位标准、面试评分和沟通话术等企业知识。

## 项目结构

```text
backend/          FastAPI、SQLAlchemy、Alembic、Celery
frontend/         React、TypeScript、Vite、Ant Design
backend/app/evaluation/  固定合成样本与 MVP 离线评测入口
docs/             项目文档
docs/study/       逐步搭建学习文档
data/local/       本地运行文件，已被 Git 忽略
docker-compose.yml
```

## 开发检查

后端使用 Conda 创建独立的 Python 3.13 环境：

```powershell
conda create -n smarthr-agent python=3.13 -y
conda activate smarthr-agent
python -m pip install -e "backend[dev,ocr]"
python -m ruff check backend
python -m pytest backend
python -m compileall -q backend\app backend\tests
```

前端：

```powershell
Set-Location frontend
npm run lint
npm run test
npm run build
```

## 固定合成样本评测

F13 固定评测集包含 3 类职位和 30 份完全合成简历，均不对应真实个人。评测集覆盖：

- 中文和英文。
- 电子 PDF、DOCX、扫描 PDF、JPG、PNG，每种格式 6 份。
- 硬条件明确通过、明确失败和信息缺失。
- 高匹配、低匹配和上下文歧义。
- 姓名、电话、邮箱、证件、地址和社交账号脱敏。

本地安装 OCR 可选依赖后执行：

```powershell
conda activate smarthr-agent
Set-Location backend
python -m app.evaluation
```

也可以在包含 OCR 依赖的 Worker 镜像中执行：

```powershell
docker compose run --rm worker python -m app.evaluation
```

评测会在临时目录生成文件，使用确定性模型桩运行实际解析、脱敏、评分、分组、证据和载荷安全逻辑，并输出 JSON 报告。生成文件和评测数据库不会写入仓库或长期运行目录。

逐步搭建学习资料保存在本地 `docs/study/`，按项目约定不纳入 Git。
