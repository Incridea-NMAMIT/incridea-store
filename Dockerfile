FROM node:24-bookworm-slim AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ENV PROD_ENV=VPS
RUN npm run build
FROM node:24-bookworm-slim
WORKDIR /app
COPY --from=build /app/dist /app/public
COPY scripts/serve.mjs /app/scripts/serve.mjs
ENV NODE_ENV=production PROD_ENV=VPS PORT=8080
USER node
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s CMD node -e "fetch('http://127.0.0.1:8080/health/ready').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node","scripts/serve.mjs"]
