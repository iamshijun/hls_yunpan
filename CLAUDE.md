# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Yunpan HLS Proxy is a Python web proxy service that uses BaiduYun (Baidu Cloud) as storage for HLS (HTTP Live Streaming) media files. It acts as a transparent proxy between media players and BaiduYun, allowing seamless playback of HLS content stored in the cloud.

**Technology Stack:**
- FastAPI with Uvicorn (ASGI server)
- httpx for async HTTP requests to BaiduYun API
- pydantic-settings for settings management
- hls.js for frontend HLS playback

## Architecture

The application follows a service-oriented architecture with clear separation of concerns:

```
Media Player → FastAPI Web Service → HLS Proxy Service → SegmentSource (Local / Yun) → BaiduYun Service
                      ↓                                            ↓
               Local Cache ←←←←←←←←←←←←←←←←←←←←←←←←←←←←← BaiduYun API
```

**Key Components:**

1. **FastAPI Application** (`app/main.py`): Provides `create_app()` factory (used by both local and Vercel entry points), lifecycle management, and service initialization. The module-level `app = create_app()` instance is shared by local uvicorn and the Vercel serverless entry.

2. **Vercel Entry** (`api/index.py`): Minimal serverless entry that just does `from app.main import app`. Vercel's `@vercel/python` runtime hosts this ASGI app directly, so local and Vercel run the exact same application.

3. **HLS Proxy Service** (`app/services/hls_proxy_service.py`): Thin request pipeline that:
   - Selects a single `SegmentSource` (local vs cloud) and serves each request from it
   - Handles m3u8 playlist and .ts chunk requests — chunks stream, playlists buffer and get URL-rewritten
   - Builds HTTP responses; internal failures raise `HLSProxyError`, mapped to JSON 500 by an exception handler
   - Wired to routes via `Depends(get_hls_service)`, which reads the service from `app.state`

4. **Segment Source** (`app/services/segment_source.py`): Content-source seam with two adapters:
   - `LocalSource`: serves HLS files from local disk
   - `YunSource`: serves from BaiduYun — converts request paths to yun paths, resolves fsids (with directory-level batch loading), reads/writes the content cache, and streams chunks
   - Local mode is authoritative: when `LOCAL_PATH` exists only local files are served, and missing files return 404 (the cloud is never contacted)

5. **BaiduYun Service** (`app/services/baiduyun_service.py`): External API integration layer (read side) that:
   - Handles BaiduYun REST API list/search/download/stream, owns endpoint URLs, token handling, and `errno` decoding in one place
   - Provides streaming download for large files
   - Upload (with exponential-backoff retry) lives in `app/services/baiduyun_upload.py` (`BaiduYunUploader`), used only by the CLI

6. **Cache Service** (`app/services/cache_service.py`): Performance optimization layer with:
   - Local file content caching to reduce API calls (controlled by `CACHE_ENABLED`)
   - TTL-based cache expiration
   - Delegates all fsid caching to an injected `FsidStore`

7. **Fsid Store** (`app/services/fsid_store.py`): Pluggable fsid persistence abstraction (`FsidStore`) with three backends selected by `create_fsid_store()`:
   - `MemoryFsidStore`: in-memory only (per-process / warm-instance lifetime)
   - `DiskFsidStore`: local disk JSON per directory, with in-memory L1 (default for local)
   - `RedisFsidStore`: Redis / Upstash (Vercel KV), shared across instances and cold starts
   - Selection priority: **Redis > disk (`CACHE_ENABLED`) > memory**

8. **M3U8 Parser** (`app/utils/m3u8_parser.py`): Owns HLS playlist URL rewriting. `rewrite_m3u8()` leaves URIs as-is so chunks resolve relative to the m3u8's own URL (prefix-agnostic — works under any nginx sub-path), and strips `#EXT-X-KEY` (encryption-key) lines by default (`keep_key=True` to keep them)

9. **Catalog Proxy** (`app/routes/catalog.py`): Forwards browser requests to an external catalog API (used by the library home page). Base URL is server-side only (`settings.catalog_api_base`) — clients cannot override it. If `settings.catalog_api_token` is set, the request carries `Authorization: Bearer <token>`. The shared `httpx.AsyncClient` from `app.state.http_client` is reused across requests, with timeout `settings.catalog_timeout`.

## Running the Application

### Quick Start
```bash
# Using the provided startup script (port from .env, default 8000)
./start.sh

# Or manually
python -m app.main
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Environment Setup
```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Configuration
Configuration is handled via `.env` file (see `.env.example` for template). `start.sh` sources `.env` before launching. Key settings:
- `ACCESS_TOKEN`: BaiduYun access token (required)
- `APP_NAME` / `APP_VERSION`: surfaced by `/` (default: `Yunpan HLS Proxy` / `1.0.0`)
- `DEBUG`: Debug mode (default: True). Also controls whether `/docs` & `/redoc` are exposed.
- `HOST`: Server host (default: 0.0.0.0)
- `PORT`: Server port (default: 8000)
- `CACHE_DIR`: Cache directory (default: ./cache)
- `CACHE_TTL`: Cache TTL in seconds (default: 3600)
- `CACHE_ENABLED`: Whether disk caching is enabled (default: True). Set to `False` on read-only filesystems (e.g. Vercel) to skip all disk writes.
- `CACHE_SEGMENTS`: Whether to cache HLS segment files (default: False)
- `YUN_PATH_PREFIX`: BaiduYun storage root for HLS files (default: /apps/movies). Request paths under `/hls/{path}` map to `<YUN_PATH_PREFIX>/{path}`.
- `LOCAL_PATH`: Local HLS file storage directory (default: ./local_hls) - if directory exists, local mode is automatically enabled
- `REDIS_URL` / `REDIS_TOKEN`: Redis / Upstash (Vercel KV) REST endpoint for cross-instance fsid storage. Also accepts Vercel/Upstash injected names via aliases: `KV_REST_API_URL`/`KV_REST_API_TOKEN` and `UPSTASH_REDIS_REST_URL`/`UPSTASH_REDIS_REST_TOKEN`. When set, fsid is stored in Redis regardless of `CACHE_ENABLED`.

- `CATALOG_API_BASE`: upstream catalog API base URL (default `http://127.0.0.1:8010`, i.e. `movie_api`).
- `CATALOG_API_TOKEN`: optional `Authorization: Bearer` token forwarded to the upstream catalog API.
- `CATALOG_TIMEOUT`: timeout in seconds for upstream catalog requests (default `10.0`).
- `HTTPX_LOG`: whether to log httpx request URLs (default: False).

Settings are managed in `config/settings.py` using pydantic-settings.

### Vercel Deployment
The project deploys to Vercel from the **repository root** (not a subfolder), so `app/` and `config/` are importable.

- Entry point: `api/index.py` (`from app.main import app`)
- Config: `vercel.json` (routes all paths to `/api/index`, sets memory/maxDuration)
- CLI scripts: root `package.json` (`vercel dev`, `vercel --prod`)

Required Vercel environment variables:
```
ACCESS_TOKEN=<baidu token>
CACHE_ENABLED=false        # Vercel filesystem is read-only except /tmp
DEBUG=false
```
Add an Upstash Redis integration (Vercel Marketplace → Storage) to persist fsid across
instances and cold starts. It injects `KV_REST_API_URL`/`KV_REST_API_TOKEN` (or
`UPSTASH_REDIS_REST_*`), which `config/settings.py` picks up automatically. Without Redis,
fsid falls back to in-memory (warm-instance only, since `CACHE_ENABLED=false`).

Note: `upstash-redis` is imported lazily inside `RedisFsidStore`, so local runs without
Redis are unaffected.

### Access Points
The web UI is static files under the top-level `movie_web/` (served separately — `hls_yunpan` does not mount a static directory).
- **Library Home**: `movie_web/index.html`
- **Play Page**: `movie_web/play.html?path={fan_code}` (details passed via URL params: `title/cover/cast/tags/year/duration/description`, comma or `|` separated)
- **Health Check**: `http://localhost:8000/health`
- **HLS Proxy**: `http://localhost:8000/hls/{path:path}`


### Upload CLI
Upload local files/directories to BaiduYun (default target root is `YUN_PATH_PREFIX`):
```bash
python -m app.upload video.ts --retries 5
python -m app.upload ./my_videos /apps/movies/my_videos -w 5
python -m app.upload ./my_videos /apps/movies/my_videos --max-size 100MB --no-resume -o overwrite
```
Upload logic (including retry) lives in `BaiduYunUploader` (`app/services/baiduyun_upload.py`); the CLI is a thin argparse shell
(progress, resume, and parallel workers). Use `--no-delete-after-upload` to keep the local file.

## Project Structure

```
hls_yunpan/
├── api/index.py            # Vercel serverless entry (from app.main import app)
├── app/
│   ├── main.py             # create_app() factory + local uvicorn boot
│   ├── routes/
│   │   ├── admin.py        # Admin endpoints
│   │   ├── catalog.py      # Catalog API proxy (/api/catalog/*)
│   │   ├── health.py       # Health check endpoint
│   │   ├── hls.py          # HLS proxy route handlers
│   │   └── metadata.py     # metadata.txt reader
│   ├── services/
│   │   ├── baiduyun_service.py   # BaiduYun REST API client (read side: list/search/download/stream)
│   │   ├── baiduyun_upload.py    # BaiduYunUploader (CLI-only upload with retry)
│   │   ├── cache_service.py      # File content cache + fsid delegation
│   │   ├── fsid_store.py         # FsidStore abstraction (Memory/Disk/Redis)
│   │   ├── hls_proxy_service.py  # Thin HLS request pipeline
│   │   ├── metadata_service.py   # metadata.txt parser
│   │   └── segment_source.py     # SegmentSource seam (LocalSource / YunSource)
│   ├── upload.py                 # Standalone CLI to upload files/dirs to BaiduYun
│   └── utils/
│       ├── m3u8_parser.py        # M3U8 rewrite (strip EXT-X-KEY)
│       ├── metadata_parser.py    # metadata.txt parser
│       └── paths.py              # HLS URL prefix / strip / local-mode helpers
├── config/settings.py      # Pydantic settings (single source)
├── ... (the frontend lives in top-level `movie_web/`, not under `web/`)
├── prototype/              # Reference prototypes — do NOT use in production
│   ├── README.md
│   ├── home.html
│   ├── home.css
│   ├── home.js
│   └── catalog_proxy.py
├── vercel.json             # Vercel deployment config
├── package.json            # Vercel CLI scripts
└── requirements.txt
```

### BaiduYun Cloud Storage
HLS files in BaiduYun should be organized under `YUN_PATH_PREFIX` (default `/apps/movies`):
```
/apps/movies/
├── video1/
|   |-- playlist.m3u8
│   ├── segment_0001
│   ├── segment_0002
│   └── ...
└── video2
```

### Local Mode
When the `LOCAL_PATH` directory exists, local mode is automatically enabled and HLS files are served from disk for development or offline use:
```
./local_hls/
├── video1/
|   |-- playlist.m3u8
│   ├── segment_0001
│   ├── segment_0002
│   └── ...
└── video2
```

### Access Patterns
Both cloud and local files are accessed through the same proxy URLs:
- `http://localhost:8000/hls/video1/playlist.m3u8`
- `http://localhost:8000/hls/video1/segment_0001`

**Local is authoritative**: when `LOCAL_PATH` exists, local mode serves every file from disk and missing files return 404 — the cloud is never contacted.

## Important Implementation Details

1. **Async Throughout**: The entire stack uses async/await for I/O operations to maximize performance with concurrent requests

2. **URL Rewriting**: The M3U8 parser (`rewrite_m3u8()`) leaves relative URIs as-is so chunks resolve relative to the m3u8's own URL (prefix-agnostic under nginx sub-paths). It drops `#EXT-X-KEY` (encryption-key) lines by default — pass `keep_key=True` to retain them.

3. **Streaming**: Large files are streamed to prevent timeouts and reduce memory usage

4. **Caching Strategy**: Two-level caching:
   - Local file content cache for downloaded content (disk, gated by `CACHE_ENABLED`)
   - Pluggable fsid cache via `FsidStore` (memory / disk / Redis), with directory-level batch loading for faster file lookups

5. **CORS**: Currently enabled for all origins (should be restricted in production deployments)

6. **Smart Local Mode**: Automatically detects and enables local mode when LOCAL_PATH directory exists:
   - No manual configuration needed
   - Serves entirely from local disk when enabled — the cloud API is never called
   - Perfect for development, testing, or offline scenarios
   - Maintains the same API interface regardless of storage backend

## Development Notes

- The project runs via `python -m app.main` (uvicorn with auto-reload when `DEBUG=true`)
- Logging is configured based on the `DEBUG` setting
- The library home (`movie_web/index.html`) and the play page (`movie_web/play.html`) are static files served separately — `hls_yunpan` does not mount a static directory. The play page uses hls.js for modern browsers and falls back to native HLS support for Safari.
- When navigating from the library to a movie, `movie_web/js/library.js` packs detail fields into the URL (cast/tags comma-joined); the play page reads them and renders immediately — there is no `/metadata/{path}` frontend fallback.
- BaiduYun API has rate limits; the caching layer helps mitigate this
- `prototype/` is a frozen reference of an earlier 3-variant prototype. Do not route production traffic through it; if you need to re-evaluate the home page, see `prototype/README.md`.

### Smart Local Mode Usage
```bash
# Simply set your local directory in .env
LOCAL_PATH=./my_videos

# Place your HLS files in the local directory
mkdir -p ./my_videos/video1
cp playlist.m3u8 ./my_videos/video1/
cp segment_* ./my_videos/video1/

# Start the service - local mode is automatically detected!
./start.sh
```
