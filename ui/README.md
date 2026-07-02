# seedwright UI

Next.js frontend (static export — no runtime Node in production; the central Spring server
serves `out/` from its static resources, ADR-0004). Create Blueprints (prefilled working demo),
trigger generation, watch job progress, browse datasets, export files.

## Development

```bash
cd ui
npm install
NEXT_PUBLIC_API_BASE=http://localhost:8080 npm run dev   # against a running central server
```

## Production build

```bash
npm run build       # emits out/ — copy into server/src/main/resources/static (or serve any way)
```
