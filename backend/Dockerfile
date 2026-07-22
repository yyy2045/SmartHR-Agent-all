FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_DEFAULT_TIMEOUT=120
ARG INSTALL_OCR=false
ARG APT_MIRROR=https://mirrors.tuna.tsinghua.edu.cn

WORKDIR /app

COPY pyproject.toml ./
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
COPY worker-entrypoint.sh ./worker-entrypoint.sh
RUN if [ "$INSTALL_OCR" = "true" ]; then \
      pip install --no-cache-dir --retries 5 '.[ocr]'; \
    else \
      pip install --no-cache-dir --retries 5 .; \
    fi

RUN if [ "$INSTALL_OCR" = "true" ]; then \
      sed -i "s|http://deb.debian.org|${APT_MIRROR}|g" \
        /etc/apt/sources.list.d/debian.sources && \
      apt-get update && \
      apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 && \
      rm -rf /var/lib/apt/lists/*; \
    fi

RUN mkdir -p /app/data/uploads

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
