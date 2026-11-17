FROM golang:1.25.0-bookworm AS crm
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY api ./api
COPY cmd ./cmd
COPY internal ./internal
COPY locales ./locales
RUN CGO_ENABLED=0 go build -trimpath -o /salescompel ./cmd/salescompel

FROM node:22-bookworm-slim AS frontend
WORKDIR /src
COPY modules/funnelhub/frontend/package*.json ./
RUN npm ci --ignore-scripts
COPY modules/funnelhub/frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY modules/funnelhub/backend/requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir -r /app/requirements.lock && useradd --uid 10001 --create-home funnelhub
COPY --from=crm /salescompel /usr/local/bin/salescompel
COPY modules/funnelhub/backend /app/modules/funnelhub/backend
COPY --from=frontend /src/dist /app/frontend/dist
COPY deploy /app/deploy
RUN mkdir -p /data && chown 10001:10001 /data
USER 10001:10001
EXPOSE 8000
CMD ["python", "/app/deploy/start.py"]
