FROM node:20-bookworm-slim AS build
WORKDIR /build/web
ENV NEXT_TELEMETRY_DISABLED=1 NEXT_OUTPUT=export
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM nginx:1.28-alpine
ENV PORT=8080 BACKEND_URL=http://salcobrand-api:8080 \
    NGINX_ENVSUBST_FILTER="^(PORT|BACKEND_URL)$"
COPY deploy/kilby/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /build/web/out /usr/share/nginx/html
# Source assets may retain restrictive modes from the remote archive extraction.
RUN chmod -R a+rX /usr/share/nginx/html
EXPOSE 8080
