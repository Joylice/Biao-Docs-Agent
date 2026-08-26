FROM docker.1ms.run/library/node:22-alpine AS build

WORKDIR /app
# Enable corepack for pnpm (node 22 ships corepack)
RUN corepack enable && corepack prepare pnpm@latest --activate
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm config set registry https://registry.npmmirror.com \
    && pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM docker.1ms.run/library/nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
