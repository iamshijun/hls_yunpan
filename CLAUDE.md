# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Yunpan HLS Proxy is a Python web proxy service that uses BaiduYun (Baidu Cloud) as storage for HLS (HTTP Live Streaming) media files. It acts as a transparent proxy between media players and BaiduYun, allowing seamless playback of HLS content stored in the cloud.

**Technology Stack:**
- FastAPI with Uvicorn (ASGI server)
- httpx for async HTTP requests to BaiduYun API
- bypy for BaiduYun API client
- pydantic for settings management
- hls.js for frontend HLS playback

## Architecture

The application follows a service-oriented architecture with clear separation of concerns:

```
Media Player → FastAPI Web Service → HLS Proxy Service → BaiduYun Service
                      ↓                                 ↓
               Local Cache ←←←←←←←←←←←←←←←←←←← BaiduYun API
```

**Key Components:**

1. **FastAPI Application** (`app/main.py`): Entry point, lifecycle management, static file mounting, and service initialization

2. **HLS Proxy Service** (`app/services/hls_proxy_service.py`): Core service that:
   - Converts HTTP request paths to BaiduYun file paths
   - Handles m3u8 playlist and .ts chunk requests
   - Rewrites URLs in m3u8 files for correct chunk references
   - Manages directory-level fsid caching for performance

3. **BaiduYun Service** (`app/services/baiduyun_service.py`): External API integration layer that:
   - Handles all communication with BaiduYun REST API
   - Implements file listing, metadata retrieval, and download operations
   - Provides streaming download for large files

4. **Cache Service** (`app/services/cache_service.py`): Performance optimization layer with:
   - Local file caching to reduce API calls
   - TTL-based cache expiration
   - fsid caching for efficient file lookups

5. **M3U8 Parser** (`app/utils/m3u8_parser.py`): Utility for parsing and generating HLS playlists

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
- `DEBUG`: Debug mode (default: True)
- `HOST`: Server host (default: 0.0.0.0)
- `PORT`: Server port (default: 8000, but start.sh uses 9009)
- `CACHE_DIR`: Cache directory (default: ./cache)
- `CACHE_TTL`: Cache TTL in seconds (default: 3600)

Settings are managed in `config/settings.py` using pydantic-settings.

### Access Points
- **Health Check**: `http://localhost:8000/health`
- **HLS Proxy**: `http://localhost:8000/hls/{path:path}`
- **Web Player**: `http://localhost:8000/web/`

## BaiduYun File Structure

HLS files in BaiduYun should be organized under `/Apps/hls/`:
```
/Apps/hls/
├── video1/
|   |-- playlist.m3u8
│   ├── segment_0001
│   ├── segment_0002
│   └── ...
└── video2
```

Access via proxy using paths like:
- `http://localhost:8000/hls/video1/playlist.m3u8`
- `http://localhost:8000/hls/video1/segment_0001`

## Important Implementation Details

1. **Async Throughout**: The entire stack uses async/await for I/O operations to maximize performance with concurrent requests

2. **URL Rewriting**: The HLS proxy service automatically rewrites URLs in m3u8 playlists to ensure correct chunk references through the proxy

3. **Streaming**: Large files are streamed to prevent timeouts and reduce memory usage

4. **Caching Strategy**: Two-level caching:
   - Local file cache for downloaded content
   - Directory-level fsid cache for faster file lookups

5. **CORS**: Currently enabled for all origins (should be restricted in production deployments)

## Development Notes

- The project uses Uvicorn with auto-reload (`--reload`) for development
- Logging is configured based on the `DEBUG` setting
- The web player at `web/index.html` uses hls.js for modern browsers and falls back to native HLS support for Safari
- BaiduYun API has rate limits; the caching layer helps mitigate this