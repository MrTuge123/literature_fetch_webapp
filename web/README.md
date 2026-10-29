# Literature Fetch website

React + Vite + TypeScript, styled with Tailwind. Sign-in uses Amplify JS (Auth only) with the
Cognito pool from the `LitFetchApi` stack; everything else is `fetch` calls to the API (`src/api.ts`).

## Run it locally

```bash
cd web
npm install                                       # first time only
python ../scripts/web_env.py --profile litfetch   # writes .env.local from the stack outputs
npm run dev                                       # http://localhost:5173
```

The API only accepts browser calls from `http://localhost:5173` (CORS, set in the API stack), so keep
that port.

## Commands

| Command | Does |
| --- | --- |
| `npm run dev` | Dev server with hot reload |
| `npm test` | Unit tests (Vitest) for the settings form |
| `npm run build` | Type-check, then build static files into `dist/` (deployed in M7) |

## Files

| File | What it is |
| --- | --- |
| `src/main.tsx`, `src/App.tsx` | Start-up and the page routes |
| `src/config.ts` | Reads `.env.local`, configures Amplify |
| `src/auth.tsx` | Who is signed in, plus their `GET /me` record |
| `src/api.ts` | `api()` — calls the API with the ID token; response types |
| `src/settings.ts` | The settings form's Zod schema and conversion to the API's format |
| `src/password.ts` | The pool's password rule |
| `src/components/` | Layout (header, nav), route guards, tag input, small UI pieces |
| `src/pages/` | Landing, Login, Settings, Digests, Account, Admin |
