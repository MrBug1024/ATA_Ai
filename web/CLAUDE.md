# Frontend Guide

- Run: `pnpm dev`
- Test: `pnpm test`
- Build: `pnpm build`
- Configure only `NEXT_PUBLIC_API_BASE_URL=http://localhost:8080`.
- Preserve the AI-first workflow: annual audit work starts in chat and links to evidence, graph and generated reports.
- Keep backend calls in `lib/backend/` and shared transport in `lib/api/client.ts`.
