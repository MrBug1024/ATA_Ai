ARG NODE_BASE_IMAGE=node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32
FROM ${NODE_BASE_IMAGE} AS base
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0

# ── Dependencies ────────────────────────────────────────────────
FROM base AS deps
# node:22-alpine is pinned to Alpine 3.24; gcompat provides libc6-compat there.
RUN apk add --no-cache gcompat=1.1.0-r4
WORKDIR /app

COPY package.json pnpm-lock.yaml ./
RUN corepack enable pnpm && pnpm install --frozen-lockfile

# ── Build ───────────────────────────────────────────────────────
FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# NEXT_PUBLIC_* values are compiled into the browser bundle by Next.js.
ARG NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL

# public/pdf.worker.min.mjs 由 postinstall 生成且被 .gitignore 排除，不在 git 构建上下文里；
# 这里从 node_modules 显式生成，确保 runner 能拷到。
RUN node -e "const{cpSync,mkdirSync}=require('fs');const p=require.resolve('pdfjs-dist/build/pdf.worker.min.mjs');mkdirSync('public',{recursive:true});cpSync(p,'public/pdf.worker.min.mjs')"

RUN corepack enable pnpm && pnpm build

# ── Production runner ────────────────────────────────────────────
FROM base AS runner
WORKDIR /app

ENV NODE_ENV=production

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
# standalone 输出不含 public/，需手动拷贝（pdf.worker.min.mjs 已在 builder 阶段生成）
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs

EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

CMD ["node", "server.js"]
