# Docker 部署 AI Berkshire Web Skill Runner

本项目内置 FastAPI Web Runner，可以在服务器上用 Docker Compose 一键启动，通过网页选择并运行 `skills/*.md` 中的 Claude Code skills。

## 1. 前置要求

服务器需要安装：

- Docker
- Docker Compose v2（`docker compose` 命令）

> 安全提醒：Web Runner 会在容器内调用 Claude Code，并可能触发文件写入、网络访问和长时间 Agent 执行。不要无认证暴露到公网。生产环境请放在 Nginx/Caddy/Cloudflare/Tailscale/Basic Auth/OAuth 后面。

## 2. 快速启动

```bash
git clone https://github.com/xbtlin/ai-berkshire.git
cd ai-berkshire
cp .env.docker.example .env.docker
```

编辑 `.env.docker`，推荐填入服务端非交互 API key：

```env
ANTHROPIC_API_KEY=sk-ant-...
```

如果使用 DeepSeek token 或其他中转服务，推荐走 **Anthropic-compatible 网关**，用环境变量指定 base URL 和模型：

```env
ANTHROPIC_API_KEY=你的_token
ANTHROPIC_BASE_URL=https://你的_anthropic_兼容网关/v1
CLAUDE_MODEL=deepseek-chat
# 或
# CLAUDE_MODEL=deepseek-reasoner
```

注意：这里的 `ANTHROPIC_BASE_URL` 必须兼容 Anthropic Messages API。DeepSeek 官方 OpenAI-compatible `/chat/completions` 接口不一定能被 Claude Code CLI 直接调用。

启动：

```bash
docker compose up -d --build
```

查看状态：

```bash
docker compose ps
docker compose logs -f web-skill-runner
```

访问：

```text
http://服务器IP:8000
```

## 3. 配置项

`.env.docker.example` 中已列出常用变量：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AI_BERKSHIRE_ROOT` | `/app` | 容器内项目根目录 |
| `AI_BERKSHIRE_VAR_DIR` | `/var/lib/ai-berkshire` | job 日志和运行时目录 |
| `CLAUDE_CLI` | `/usr/local/bin/claude` | Claude Code CLI 路径 |
| `CLAUDE_MODEL` | 空 | 可选，透传为 `claude --model`，例如 `claude-opus-4-8`、`deepseek-chat` |
| `AI_BERKSHIRE_JOB_TIMEOUT` | `1800` | 单任务超时秒数 |
| `AI_BERKSHIRE_MAX_ARGUMENT_LENGTH` | `12000` | 参数最大长度 |
| `AI_BERKSHIRE_PERMISSION_MODE` | `default` | Claude Code permission mode |
| `AI_BERKSHIRE_SKIP_PERMISSIONS` | `0` | 设为 `1` 会追加 `--dangerously-skip-permissions` |
| `ANTHROPIC_API_KEY` | 空 | 推荐的服务器非交互认证方式 |
| `ANTHROPIC_BASE_URL` | 空 | 可选，Anthropic-compatible 网关地址 |

如果设置 `AI_BERKSHIRE_SKIP_PERMISSIONS=1`，Claude Code 将跳过权限确认。只有在容器和 HTTP 入口都被严格保护时才建议开启。

## 4. 持久化目录

`docker-compose.yml` 默认挂载：

```yaml
./reports:/app/reports
ai_berkshire_var:/var/lib/ai-berkshire
claude_config:/home/appuser/.claude
anthropic_config:/home/appuser/.config/anthropic
```

含义：

- `./reports`：报告输出，保留在宿主机仓库目录中。
- `ai_berkshire_var`：Web Runner job 日志和运行时状态。
- `claude_config`：Claude Code 配置和安装后的 commands。
- `anthropic_config`：预留给 Anthropic CLI/OAuth profile 类配置。

Entrypoint 每次启动都会执行：

```bash
CLAUDE_COMMANDS_DIR=$HOME/.claude/commands ./scripts/install-claude-commands.sh
```

因此即使 `claude_config` volume 覆盖了镜像内的 `.claude` 目录，skills 也会在容器启动时重新同步。

## 5. 验证命令

构建：

```bash
docker compose build
```

检查 Claude Code：

```bash
docker compose run --rm web-skill-runner claude --version
```

检查 Python 模块：

```bash
docker compose run --rm web-skill-runner python -m py_compile server/*.py
```

检查 Skill 扫描：

```bash
docker compose run --rm web-skill-runner python -c "from server.skills import SkillRegistry; from server.config import settings; print(len(SkillRegistry(settings.skills_dir).list_skills()))"
```

检查 commands 是否安装：

```bash
docker compose run --rm web-skill-runner ls -la /home/appuser/.claude/commands
```

启动后健康检查：

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/api/skills
```

## 6. 反向代理建议

生产环境不要直接暴露 `8000`。

可以把 compose 端口改成只监听本机：

```yaml
ports:
  - "127.0.0.1:8000:8000"
```

然后用 Nginx/Caddy 反代，并加 HTTPS + Basic Auth/OAuth。

Caddy 示例：

```caddyfile
your-domain.example.com {
  basicauth {
    your-user $2a$14$replace-with-caddy-hash
  }
  reverse_proxy 127.0.0.1:8000
}
```

## 7. 升级

```bash
git pull --rebase origin main
docker compose up -d --build
```

## 8. 备份

重点备份：

- `reports/`
- Docker volume：`ai_berkshire_var`
- Docker volume：`claude_config`（可能包含敏感配置）

## 9. 常见问题

### 页面能打开，但运行 skill 报 Claude auth 错误

优先确认 `.env.docker` 是否设置了：

```env
ANTHROPIC_API_KEY=sk-ant-...
```

然后重启：

```bash
docker compose up -d
```

### 看不到 skills

检查容器内 commands：

```bash
docker compose exec web-skill-runner ls -la /home/appuser/.claude/commands
```

也可以检查 API：

```bash
curl http://127.0.0.1:8000/api/skills
```

### 报告没有出现在宿主机

确认 compose 里有：

```yaml
- ./reports:/app/reports
```

容器内写入 `/app/reports` 的文件会出现在宿主机 `./reports`。
