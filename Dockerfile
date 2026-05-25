FROM node:22-alpine AS frontend-build

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=8006 \
    DB_PATH=/app/backend/database-prd.db \
    FRONTEND_DIST_PATH=/app/frontend-dist

WORKDIR /app/backend

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY app-profiles/ /app/app-profiles
COPY shared/ /app/shared
COPY --from=frontend-build /app/frontend/dist /app/frontend-dist

EXPOSE 8006

CMD ["python", "main.py"]
