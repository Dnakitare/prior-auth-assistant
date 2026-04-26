# Frontend production image. Two stages: vite build → nginx serve.
# Designed to deploy on Railway / any platform that injects $PORT.

FROM node:20-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .

# VITE_API_URL is inlined into the JS bundle at build time. Pass it via
# `docker build --build-arg VITE_API_URL=https://...` (or set it as a
# build env var on Railway / Cloudflare Pages).
ARG VITE_API_URL
ENV VITE_API_URL=${VITE_API_URL}

RUN npm run build

# ---- runtime ----
FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

# nginx:alpine's entrypoint already handles /etc/nginx/templates → envsubst
# substitution, so $PORT (and only $PORT here) gets replaced at boot.
ENV PORT=80

EXPOSE 80

# Default entrypoint already does envsubst + exec nginx -g "daemon off;"
