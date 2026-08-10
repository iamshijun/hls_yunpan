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

1. **FastAPI Application** (`app/main.py`): Provides `create_app()` factory (used by both local and Vercel entry points), lifecycle management, static file mounting, and service initialization. The module-level `app = create_app()` instance is shared by local uvicorn and the Vercel serverless entry.

2. **Vercel Entry** (`api/index.py`): Minimal serverless entry that just does `from app.main import app`. Vercel's `@vercel/python` runtime hosts this ASGI app directly, so local and Vercel run the exact same application.

3. **HLS Proxy Service** (`app/services/hls_proxy_service.py`): Thin request pipeline that:
   - Composes `SegmentSource` adapters (local vs cloud) and serves each request from the first that can
   - Handles m3u8 playlist and .ts chunk requests — chunks stream, playlists buffer and get URL-rewritten
   - Builds HTTP responses; internal failures raise `HLSProxyError`, mapped to JSON 500 by an exception handler
   - Wired to routes via `Depends(get_hls_service)`, which reads the service from `app.state`

4. **Segment Source** (`app/services/segment_source.py`): Content-source seam with two adapters:
   - `LocalSource`: serves HLS files from local disk
   - `YunSource`: serves from BaiduYun — converts request paths to yun paths, resolves fsids (with directory-level batch loading), reads/writes the content cache, and streams chunks
   - Local mode is authoritative: when `LOCAL_PATH` exists only local files are served, and missing files return 404 (the cloud is never contacted)

5. **BaiduYun Service** (`app/services/baiduyun_service.py`): External API integration layer that:
   - Handles all communication with BaiduYun REST API (list, meta, download, stream, upload)
   - Provides streaming download for large files and uploads with exponential-backoff retry (`upload_file` / `upload_bytes`)
   - Owns endpoint URLs, token handling, and `errno` decoding in one place

6. **Cache Service** (`app/services/cache_service.py`): Performance optimization layer with:
   - Local file content caching to reduce API calls (controlled by `CACHE_ENABLED`)
   - TTL-based cache expiration
   - Delegates all fsid caching to an injected `FsidStore`

7. **Fsid Store** (`app/services/fsid_store.py`): Pluggable fsid persistence abstraction (`FsidStore`) with three backends selected by `create_fsid_store()`:
   - `MemoryFsidStore`: in-memory only (per-process / warm-instance lifetime)
   - `DiskFsidStore`: local disk JSON per directory, with in-memory L1 (default for local)
   - `RedisFsidStore`: Redis / Upstash (Vercel KV), shared across instances and cold starts
   - Selection priority: **Redis > disk (`CACHE_ENABLED`) > memory**

8. **M3U8 Parser** (`app/utils/m3u8_parser.py`): Owns HLS playlist parsing and URL rewriting. `rewrite()` rewrites relative URIs in bare lines and tag attributes (`#EXT-X-MAP` / `#EXT-X-MEDIA`), and strips `#EXT-X-KEY` (encryption-key) lines by default (`keep_key=True` to keep and rewrite them)

## Running the Application

### Quick Start
```bash
# Using the provided startup script (runs on port 9009)
./start.sh

# Or manually
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
Configuration is handled via `.env` file (see `.env.example` for template). Key settings:
- `ACCESS_TOKEN`: BaiduYun access token (required)
- `DEBUG`: Debug mode (default: True). Also controls whether `/docs` & `/redoc` are exposed.
- `HOST`: Server host (default: 0.0.0.0)
- `PORT`: Server port (default: 8000, but start.sh uses 9009)
- `CACHE_DIR`: Cache directory (default: ./cache)
- `CACHE_TTL`: Cache TTL in seconds (default: 3600)
- `CACHE_ENABLED`: Whether disk caching is enabled (default: True). Set to `False` on read-only filesystems (e.g. Vercel) to skip all disk writes.
- `CACHE_SEGMENTS`: Whether to cache HLS segment files (default: False)
- `YUN_PATH_PREFIX`: BaiduYun storage root for HLS files (default: /apps/movies). Request paths under `/hls/{path}` map to `<YUN_PATH_PREFIX>/{path}`.
- `LOCAL_PATH`: Local HLS file storage directory (default: ./local_hls) - if directory exists, local mode is automatically enabled
- `REDIS_URL` / `REDIS_TOKEN`: Redis / Upstash (Vercel KV) REST endpoint for cross-instance fsid storage. Also accepts Vercel/Upstash injected names via aliases: `KV_REST_API_URL`/`KV_REST_API_TOKEN` and `UPSTASH_REDIS_REST_URL`/`UPSTASH_REDIS_REST_TOKEN`. When set, fsid is stored in Redis regardless of `CACHE_ENABLED`.

Settings are managed in `config/settings.py` using pydantic-settings.

### Vercel Deployment
The project deploys to Vercel from the **repository root** (not a subfolder), so `app/`, `config/`, and `web/` are all importable.

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
- **Health Check**: `http://localhost:8000/health`
- **HLS Proxy**: `http://localhost:8000/hls/{path:path}`
- **Web Player**: `http://localhost:8000/web` 

**网络访问**:
- 启动时会显示本地和网络访问地址
- 其他机器可以通过服务器的IP地址直接访问web播放器

### Upload CLI
Upload local files/directories to BaiduYun (default target root is `YUN_PATH_PREFIX`):
```bash
python -m app.upload video.ts --retries 5
python -m app.upload ./my_videos /apps/movies/my_videos -w 5
python -m app.upload ./my_videos /apps/movies/my_videos --max-size 100MB --no-resume -o overwrite
```
Upload logic (including retry) lives in `BaiduYunService`; the CLI is a thin argparse shell
(progress, resume, and parallel workers). Use `--no-delete-after-upload` to keep the local file.

## Project Structure

```
hls_yunpan/
├── api/index.py            # Vercel serverless entry (from app.main import app)
├── app/
│   ├── main.py             # create_app() factory + local uvicorn boot
│   ├── routes/
│   │   ├── hls.py          # HLS proxy route handlers
│   │   └── health.py       # Health check endpoint
│   ├── services/
│   │   ├── baiduyun_service.py   # BaiduYun REST API client (list/download/stream/upload)
│   │   ├── cache_service.py      # File content cache + fsid delegation
│   │   ├── fsid_store.py         # FsidStore abstraction (Memory/Disk/Redis)
│   │   ├── hls_proxy_service.py  # Thin HLS request pipeline
│   │   └── segment_source.py     # SegmentSource seam (LocalSource / YunSource)
│   ├── upload.py                 # Standalone CLI to upload files/dirs to BaiduYun
│   └── utils/
│       └── m3u8_parser.py        # HLS playlist parse / rewrite / generate
├── config/settings.py      # Pydantic settings (single source)
├── web/index.html          # Static web player
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

2. **URL Rewriting**: The M3U8 parser (`M3U8Parser.rewrite()`) rewrites playlist URLs so chunks resolve through the proxy. It handles relative URIs in bare lines and tag attributes, and drops `#EXT-X-KEY` (encryption-key) lines by default — pass `keep_key=True` to retain and rewrite them.

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

- The project uses Uvicorn with auto-reload (`--reload`) for development
- Logging is configured based on the `DEBUG` setting
- The web player at `web/index.html` uses hls.js for modern browsers and falls back to native HLS support for Safari
- BaiduYun API has rate limits; the caching layer helps mitigate this

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
