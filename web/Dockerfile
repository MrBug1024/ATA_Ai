FROM node:22-alpine AS base

# ── Dependencies ────────────────────────────────────────────────
FROM base AS deps
RUN apk add --no-cache libc6-compat
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
