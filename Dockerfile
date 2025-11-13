FROM python:3.11-slim

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ENV POETRY_VERSION=2.2.1
ENV POETRY_HOME=/opt/poetry
ENV POETRY_VIRTUALENVS_CREATE=false
ENV PATH="${POETRY_HOME}/bin:${PATH}"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install --no-install-recommends --yes curl \
    && curl -sSL https://install.python-poetry.org | python3 - \
    && apt-get purge --yes curl \
    && apt-get autoremove --yes \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml poetry.lock /app/

RUN poetry install

COPY src /app/src

EXPOSE 8080 9100

ENV BLOCKCHAIN_EXPORTER_CONFIG_PATH=/app/config/config.toml
ENV HEALTH_PORT=8080
ENV METRICS_PORT=9100

ENTRYPOINT ["poetry", "run", "python", "-m", "blockchain_exporter.main"]
