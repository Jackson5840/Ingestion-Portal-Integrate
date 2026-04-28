# Integrated Docker Startup

This compose file starts the three project services together:

- `are`: ingestion/release API and UI
- `swc2pvec`: SWC to persistence-vector API
- `similarity-search`: similarity and duplicate-detection API
- shared `redis`, `postgres`, and `mysql` containers

Start it from this directory:

```bash
cp .env.example .env
docker compose up --build
```

By default, ARE reads and writes local data under
`/home/kira/app/Ingestion/data`. The compose file mounts this host directory into
the ARE container at the same absolute path.

Default URLs:

- ARE UI/API: http://localhost:5000
- Similarity API: http://localhost:5003
- SWC2PVec API: http://localhost:5017

Quick checks after startup:

```bash
docker compose ps
docker compose exec -T are python3 -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:5000/', timeout=5).read().decode())"
docker compose exec -T are python3 -c "import urllib.request; print(urllib.request.urlopen('http://swc2pvec:5000/', timeout=5).read().decode())"
docker compose exec -T are python3 -c "import urllib.request; print(urllib.request.urlopen('http://similarity-search:5000/clearcache', timeout=5).read().decode())"
```

`similarity-search` does not define a `/` route, so `http://localhost:5003/`
returns 404 even when the service is running. Use its concrete API routes such as
`/clearcache`, `/getDuplicatesfordata/`, or `/similarNeurons/...`.

Important: `similarity-search` is started with `SIS_INIT_ON_STARTUP=0` by default because the repository does not include the `.pkl` cache files referenced by its Dockerfile history, and a fresh MySQL container does not contain the NeuroMorpho schema/data it expects. Set it to `1` after loading the expected MySQL data or adding cache files.
