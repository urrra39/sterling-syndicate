FROM python:3.11-slim

WORKDIR /app

# Install Docker CLI so backend can talk to DinD sandbox daemon
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    ca-certificates \
    && curl -fsSL https://download.docker.com/linux/static/stable/x86_64/docker-27.3.1.tgz \
       | tar -xz -C /usr/local/bin --strip-components=1 docker/docker \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Prefer wheels; greenlet must not compile from source in slim images without full toolchain quirks
RUN pip install --no-cache-dir --only-binary=:all: greenlet==3.1.1 \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Respect $PORT when the platform injects one (Render, Cloud Run, Heroku, ...),
# otherwise default to 8000 for docker-compose and local runs. Run migrations
# first so the schema is current before the app accepts traffic. Shell form is
# required for env-var expansion.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
