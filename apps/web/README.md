# Web dashboard (Next.js)

```bash
cd apps/web
npm install
npm run dev        # http://localhost:3000  (API must run on :8000)
```
Set `API_URL` if the API is elsewhere. Requests to `/api/*` are proxied to FastAPI (see `next.config.js`).
