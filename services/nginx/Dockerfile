FROM nginx:1.25-alpine

# Remove default nginx config
RUN rm /etc/nginx/conf.d/default.conf 2>/dev/null || true

# Copy our nginx config
COPY nginx.conf /etc/nginx/nginx.conf

# Copy static frontend files
COPY frontend/ /usr/share/nginx/html/

# Script that generates config.js from env vars before nginx starts.
# Files in /docker-entrypoint.d/ are executed in alphabetical order
# by the official nginx image entrypoint.
COPY entrypoint.sh /docker-entrypoint.d/40-generate-config.sh
# Strip Windows CRLF line endings so the shebang works on Linux
RUN sed -i 's/\r$//' /docker-entrypoint.d/40-generate-config.sh \
 && chmod +x /docker-entrypoint.d/40-generate-config.sh

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q --spider http://127.0.0.1/config.js || exit 1
