# SmartHR-Agent-all

面向招聘专员的 AI 简历筛选 MVP。项目提供职位与版本化筛选标准、批量简历解析、敏感信息脱敏、AI 人岗匹配、人工决策、候选人对比、修正重跑、审计和安全删除闭环。

## MVP 能力

- 单招聘专员账号登录、HttpOnly Cookie 会话和前端路由保护。
- 职位管理、人工筛选标准、AI JD 草稿和不可变标准版本。
- 单批最多 50 份 PDF、DOCX、JPG、PNG 简历上传与逐文件状态。
- PDF/DOCX 文本提取、扫描件和图片 OCR、失败隔离与重试。
- 创建简历批次时可选择将解析原文或本地脱敏文本发送给 AI，默认发送原文且创建后不可修改。
- 硬条件三态判断、自动淘汰、分维度评分、证据引用与人工改判。
- 最多 3 名同职位、同标准、同分析版本候选人横向对比。
- 候选人档案修正、单人重跑、整批重跑和历史版本保留。
- 登录、原文件访问、标准确认、自动淘汰恢复、人工决策和重跑审计。
- 批次二次确认永久删除、数据库级联清理和文件删除失败补偿。

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

登录会话使用 HttpOnly Cookie，服务端会话保存在 Redis。登录页、认证状态恢复和业务路由保护已经接入前端。除登录和健康检查外，业务接口均要求有效会话，并按招聘专员的职位归属校验数据访问。

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
