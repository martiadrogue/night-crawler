# --- STAGE 1: Base Environment ---
FROM python:3.11-slim AS base

WORKDIR /apps/martiadrogue/night-crawler/frontend

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# The app package lives in src/ (src layout, like the backend's).
ENV PYTHONPATH=/apps/martiadrogue/night-crawler/frontend/src

ARG USERNAME=nightcrawler-frontend
ARG USER_UID=1000
ARG USER_GID=$USER_UID

RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID -m $USERNAME

# curl/unzip/ca-certificates: `reflex init` downloads its own Node.js and
# bun at build time, so the running container never needs the internet.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    unzip \
    && rm -rf /var/lib/apt/lists/*


# --- STAGE 2: Development Builder ---
FROM base AS builder-dev

COPY frontend/requirements.txt frontend/requirements-dev.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements-dev.txt


# --- STAGE 3: Development Runtime Target ---
FROM base AS development

COPY --from=builder-dev /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder-dev /usr/local/bin /usr/local/bin

COPY --chown=$USER_UID:$USER_GID frontend/ ./

# Bakes the Node/bun toolchain and the JS dependencies into .web/ at build
# time. The dev override bind-mounts the source over this but leaves .web/
# alone, so the bake is reused across `docker compose up` runs.
RUN reflex init && chown -R $USER_UID:$USER_GID .

EXPOSE 3000 8000
USER nightcrawler-frontend

CMD ["reflex", "run", "--env", "dev"]

