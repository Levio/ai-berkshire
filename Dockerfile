FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AI_BERKSHIRE_ROOT=/app \
    AI_BERKSHIRE_VAR_DIR=/var/lib/ai-berkshire \
    CLAUDE_CLI=/usr/local/bin/claude \
    HOME=/home/appuser

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        git \
        nodejs \
        npm \
        tini \
    && npm install -g @anthropic-ai/claude-code \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10001 appuser \
    && useradd --uid 10001 --gid appuser --create-home --shell /bin/bash appuser

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY server ./server
COPY skills ./skills
COPY tools ./tools
COPY scripts/install-claude-commands.sh ./scripts/install-claude-commands.sh
COPY CLAUDE.md AGENTS.md ./
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
    && chmod +x ./scripts/install-claude-commands.sh \
    && find ./tools -maxdepth 1 -type f \( -name "*.py" -o -name "*.sh" \) -exec chmod +x {} +

RUN mkdir -p /app/reports /var/lib/ai-berkshire /home/appuser/.claude /home/appuser/.config/anthropic \
    && chown -R appuser:appuser /app /var/lib/ai-berkshire /home/appuser

USER appuser

EXPOSE 8000

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]
