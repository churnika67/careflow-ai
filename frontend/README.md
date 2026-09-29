# CareFlow AI — frontend

Next.js/TypeScript foundation for the CareFlow AI web interface. See
[../docs/phase14_frontend_design.md](../docs/phase14_frontend_design.md)
for the full design, architecture, and scope of what is (and isn't) built
so far, and the root [README](../README.md) for how to run the backend
this frontend talks to.

## Setup

```bash
npm install
cp .env.example .env.local   # adjust the port if your backend is not on 8000
```

## Scripts

| Command | Purpose |
| --- | --- |
| `npm run dev` | Start the development server at http://localhost:3000 |
| `npm run build` | Production build |
| `npm start` | Serve the production build |
| `npm run lint` | ESLint |
| `npm run typecheck` | `tsc --noEmit` |
| `npm test` | Vitest (unit/component tests, no real backend required) |
