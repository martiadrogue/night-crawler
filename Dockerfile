# --- STAGE 1: Base Environment ---
FROM python:3.11-slim AS base

WORKDIR /apps/martiadrogue/night-crawler

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# Fixed, non-home location so the Chromium binary downloaded during the
# image build is reachable regardless of which user launches it at runtime.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

ARG USERNAME=nightcrawler-app
ARG USER_UID=1000
ARG USER_GID=$USER_UID

RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID -m $USERNAME

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /var/log/night_crawler && chown -R $USERNAME:$USERNAME /var/log/night_crawler
RUN mkdir -p /var/lib/night_crawler/csv/raw /var/lib/night_crawler/csv/validated && chown -R $USERNAME:$USERNAME /var/lib/night_crawler/csv


# --- STAGE 2: Development Builder ---
FROM base AS builder-dev

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
RUN mkdir -p backend/src/night_crawler && touch backend/src/night_crawler/__init__.py

RUN pip install --no-cache-dir --upgrade pip \
    && pip install ".[dev]" --no-cache-dir .


# --- STAGE 3: Development Runtime Target ---
FROM base AS development

COPY --from=builder-dev /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder-dev /usr/local/bin /usr/local/bin

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    jq \
    && rm -rf /var/lib/apt/lists/*

COPY ./backend/src ./backend/src
COPY pyproject.toml README.md ./
RUN pip install -e . --no-deps

# Patchright is a source-level Playwright fork, not a separate driver, so
# it honors the same PLAYWRIGHT_BROWSERS_PATH the line above already set -
# both installs land side by side in it, and the one chmod below covers both.
RUN playwright install --with-deps chromium \
    && patchright install --with-deps chromium \
    && chmod -R o+rX "$PLAYWRIGHT_BROWSERS_PATH"

EXPOSE 8000
USER nightcrawler-app

CMD ["uvicorn", "night_crawler.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

