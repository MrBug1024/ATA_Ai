# Frontend Agent Guide

## Scope

The frontend preserves the original AI conversation experience for annual financial statement audit. Users work through chat and can open project materials, evidence, relationship graphs, corrections, reports and administration from the same application.

## Commands

```powershell
pnpm dev
pnpm test
pnpm build
pnpm test:e2e
```

## Configuration

Configure one public backend address only:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8080
```

Never put secrets in a `NEXT_PUBLIC_*` variable. All backend calls go through `lib/backend/` and the shared authenticated transport in `lib/api/client.ts`.

## Architecture

- `app/`: Next.js pages and routes.
- `components/chat/`: primary AI conversation UI.
- `components/cases/`: annual project materials and corrections.
- `components/knowledge-graph/`: graph, evidence and source-page views.
- `lib/backend/`: typed annual backend operations.
- `lib/assistant-ui/`: SSE runtime and attachments.
- `lib/hooks/`: SWR queries and mutations.

Preserve bearer-token origin checks, SSE event handling, attachment normalization, evidence links and responsive layout. Add or update Vitest coverage for contract changes and run a production build before handoff.
