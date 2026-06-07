# AI-DM Tabletop Console

Canonical local frontend for the AI-DM Flask backend.

## Run

From the repo root, start the backend:

```bash
./scripts/run_local_backend.sh
```

Then run the frontend:

```bash
cd aidm_frontend
npm ci
npm run dev -- --host 127.0.0.1
```

Open:

```text
http://127.0.0.1:5173/
```

The default backend URL is blank, which means same-origin. In dev, Vite proxies
`/api/*` and `/socket.io/*` to `http://127.0.0.1:5050`. Override that proxy with
`VITE_AIDM_PROXY_TARGET` when the backend runs somewhere else:

```bash
VITE_AIDM_PROXY_TARGET=http://127.0.0.1:5050 npm run dev -- --host 127.0.0.1
```

For a one-link playtest, serve the built frontend from Flask instead of running
Vite separately:

```bash
cd ..
make unified
```

When using the unified server, leave Backend Settings' Backend URL blank. Share
links then only need the public app URL plus `campaign` and `session`; players do
not need to paste a separate backend URL.

## Checks

```bash
npm test
npm run lint
npm run typecheck
npm run build
npm run bundle:budget
npm audit --omit=dev
```

## Notes

- The client reads campaigns, sessions, players, maps, segments, session state,
  logs, worlds, canon, turn events, and beta metrics from the REST API.
- Live play uses Socket.IO events: `join_session`, `send_message`,
  `dm_response_start`, `dm_chunk`, `dm_response_end`, `roll_required`, and
  `turn_status`, `session_log_update`.
- The UI intentionally does not send a test turn automatically, so it will not
  mutate a live campaign just by loading.
- Auth tokens are kept in `sessionStorage` for the current tab session. The
  legacy `localStorage` key is migrated and cleared when the app loads.
