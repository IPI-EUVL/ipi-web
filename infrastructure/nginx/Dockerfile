FROM node:24-alpine AS frontend-build

WORKDIR /build

COPY apps/webview/frontend/package.json apps/webview/frontend/package-lock.json ./
RUN npm ci

COPY apps/webview/frontend/ ./
ARG VITE_GRAFANA_URL=http://localhost:3000/
RUN VITE_GRAFANA_URL="$VITE_GRAFANA_URL" npm run build

FROM nginx:1.29-alpine

ARG API_UPSTREAM=host.docker.internal:8000

COPY infrastructure/nginx/default.conf.template /tmp/default.conf.template
RUN API_UPSTREAM="$API_UPSTREAM" envsubst '${API_UPSTREAM}' \
	< /tmp/default.conf.template \
	> /etc/nginx/conf.d/default.conf \
	&& rm /tmp/default.conf.template

COPY --from=frontend-build /build/dist /usr/share/nginx/html