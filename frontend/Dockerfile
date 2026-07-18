# ── Stage 1: Build ────────────────────────────────────────────────────
FROM node:20-alpine AS build

WORKDIR /app

# Install deps from a clean, reproducible lockfile.
COPY package.json package-lock.json* ./
RUN npm ci

# The API origin is baked into the bundle at build time (Vite inlines
# import.meta.env.VITE_* during `npm run build`). Supply it via --build-arg so
# the same image source can target any deployment. Defaults to the compose
# service URL for local builds.
ARG VITE_API_URL=http://127.0.0.1:8000
ENV VITE_API_URL=${VITE_API_URL}

# Compile the production bundle into /app/dist.
COPY . .
RUN npm run build

# ── Stage 2: Serve ────────────────────────────────────────────────────
# Lightweight, non-root nginx worker serving ONLY the compiled static assets.
# No Node runtime, no dev server, no source — just the dist/ artifacts.
FROM nginx:1.27-alpine

# Drop the stock config and install our hardened one (CSP, HSTS, etc.).
RUN rm -rf /etc/nginx/conf.d/*
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy only the build artifacts from stage 1.
COPY --from=build /app/dist /usr/share/nginx/html

# Run as the unprivileged nginx user (uid 101). Because a non-root process can't
# bind privileged ports (<1024), the server listens on 8080. Rewire the main
# nginx.conf to run in the foreground without needing root to write its pidfile.
RUN sed -i 's,listen\s*80;,listen 8080;,' /etc/nginx/conf.d/default.conf \
    && sed -i '/user  nginx;/d' /etc/nginx/nginx.conf \
    && sed -i 's,/var/run/nginx.pid,/tmp/nginx.pid,' /etc/nginx/nginx.conf \
    && chown -R nginx:nginx /usr/share/nginx/html /var/cache/nginx \
    && chmod -R o-rwx /usr/share/nginx/html

USER nginx

EXPOSE 8080

# Basic liveness probe against the served SPA.
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -q --spider http://127.0.0.1:8080/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
