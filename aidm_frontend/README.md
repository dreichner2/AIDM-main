# AI-DM Tabletop Console

Alternate local frontend for the AI-DM Flask backend.

## Run

From the repo root, start the backend:

```bash
./scripts/run_local_backend.sh
```

Then run the frontend:

```bash
cd aidm_frontend
npm install
npm run dev -- --host 127.0.0.1
```

Open:

```text
http://127.0.0.1:5173/
```

The default backend URL is `http://127.0.0.1:5050`. Override it at dev/build
time with `VITE_AIDM_API_BASE_URL`:

```bash
VITE_AIDM_API_BASE_URL=http://127.0.0.1:5050 npm run dev -- --host 127.0.0.1
```

## Checks

```bash
npm run lint
npm run typecheck
npm run build
npm run bundle:budget
```

## Notes

- The client reads campaigns, sessions, players, maps, segments, session state,
  logs, and beta metrics from the REST API.
- Live play uses Socket.IO events: `join_session`, `send_message`,
  `dm_response_start`, `dm_chunk`, `dm_response_end`, `roll_required`, and
  `session_log_update`.
- The UI intentionally does not send a test turn automatically, so it will not
  mutate a live campaign just by loading.
