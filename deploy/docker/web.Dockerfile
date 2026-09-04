# The single front door: the built SPA, plus the proxy rules the API needs. NPM (or any other
# reverse proxy) then has one upstream to point at instead of two.
FROM node:20-alpine AS build

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
# The registry times out from this node often enough that the default single attempt loses a
# ten-minute build to a transient socket error.
RUN npm ci --no-audit --no-fund --fetch-retries 5 --fetch-retry-maxtimeout 120000 --fetch-timeout 600000
COPY frontend/ ./
RUN npm run build


FROM nginx:alpine

COPY deploy/docker/web.nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080
