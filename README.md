# SmartHR-Agent-all

面向招聘专员的 AI 简历筛选 MVP。当前已完成 React、FastAPI、PostgreSQL、Redis、Celery 和 Docker Compose 工程骨架。

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

## 项目结构

```text
backend/          FastAPI、SQLAlchemy、Alembic、Celery
frontend/         React、TypeScript、Vite、Ant Design
docs/             项目文档
docs/study/       逐步搭建学习文档
data/local/       本地运行文件，已被 Git 忽略
docker-compose.yml
```

## 开发检查

后端：

```powershell
.\.venv\Scripts\python.exe -m ruff check backend
.\.venv\Scripts\python.exe -m pytest backend
```

前端：

```powershell
Set-Location frontend
npm run lint
npm run test
npm run build
```

逐步搭建学习资料保存在本地 `docs/study/`，按项目约定不纳入 Git。
