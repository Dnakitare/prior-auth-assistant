# Prior Authorization Assistant — frontend

React 19 + TypeScript + Vite + Tailwind. Talks to the FastAPI backend in the
repo root; see the [main README](../README.md) for the full architecture.

```bash
npm install
npm run dev        # expects the API on http://localhost:8000
npm run build      # tsc -b && vite build
npm run lint
```

`VITE_API_URL` sets the API origin at build time and is required for
production builds (the build fails loudly without it rather than baking in a
localhost fallback). The shared demo API key is baked in as the default;
it is intentionally public and scoped to the synthetic demo tenant.

`public/_headers` carries the CSP and security headers served by Cloudflare
Pages. If you change the API origin, update `connect-src` there too.
