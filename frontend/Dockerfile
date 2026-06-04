# Multi-stage frontend build.
# Stage 1: build with Node 20 Alpine
# Stage 2: serve with nginx Alpine

# ─── Stage 1: Build ───────────────────────────────────────────────────────────
FROM node:20-alpine AS build

WORKDIR /app

# Install deps first (separate layer — cache-friendly on dep-only changes)
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --ignore-scripts

# Copy source and build
COPY frontend/ .

# VITE_API_BASE is empty by default so the SPA uses same-origin relative paths.
# Pass --build-arg VITE_API_BASE=http://... to override for non-proxied setups.
ARG VITE_API_BASE=""
ENV VITE_API_BASE=${VITE_API_BASE}

RUN npm run build

# ─── Stage 2: Serve ───────────────────────────────────────────────────────────
FROM nginx:1.27-alpine AS serve

# Remove nginx default config
RUN rm /etc/nginx/conf.d/default.conf

# Copy our SPA-aware nginx config
COPY frontend/nginx.conf /etc/nginx/conf.d/app.conf

# Copy the built assets from the build stage
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
