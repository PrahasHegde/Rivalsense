FROM node:24.11.1-bookworm-slim AS frontend
WORKDIR /build
COPY frontEnd/package.json frontEnd/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontEnd/index.html frontEnd/vite.config.js ./
COPY frontEnd/src ./src
COPY frontEnd/public ./public
COPY frontEnd/scripts/validate-public-config.mjs ./scripts/validate-public-config.mjs
# Public values only. Never declare a Context.dev or secret Supabase build ARG.
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_PUBLISHABLE_KEY
ENV VITE_API_BASE_URL=""
RUN node scripts/validate-public-config.mjs && npm run build

FROM python:3.13-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FRONTEND_DIST=/app/static
WORKDIR /app
COPY Backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 10001 rivalsense
COPY Backend/app ./app
COPY --from=frontend /build/dist ./static
USER rivalsense
EXPOSE 10000
# Exactly one worker: demo read limits are process-local. No migration command.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1"]
