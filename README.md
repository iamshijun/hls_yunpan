# Yunpan HLS Proxy

使用百度网盘作为HLS媒体文件存储的Python Web代理服务。

## 架构设计

```
播放器请求
    ↓
FastAPI Web服务
    ↓
请求解析 & 路径转换
    ↓
百度网盘API
    ↓
本地缓存 (可选)
    ↓
返回给播放器
```

## 核心功能

- **透明代理**: 播放器无需感知实际存储方式
- **百度网盘集成**: 通过API直接从网盘获取文件
- **HLS支持**: 完整支持m3u8播放列表和ts分片文件
- **本地缓存**: 减少网盘API调用，提升性能
- **URL重写**: 自动处理m3u8中的相对路径

## 项目结构

```
hls_yunpan/
├── api/
│   └── index.py               # Vercel serverless 入口 (from app.main import app)
├── app/
│   ├── main.py                # create_app() 工厂 + 本地 uvicorn 启动
│   ├── routes/
│   │   ├── admin.py           # 管理路由
│   │   ├── catalog.py         # 目录 API 代理（生产，/api/catalog/*）
│   │   ├── health.py          # 健康检查
│   │   ├── hls.py             # HLS 代理路由
│   │   └── metadata.py        # metadata.txt 读取路由
│   ├── services/
│   │   ├── baiduyun_service.py    # 百度网盘服务（列表/下载/流式/上传）
│   │   ├── cache_service.py       # 文件内容缓存 + fsid 委托
│   │   ├── fsid_store.py          # fsid 存储抽象 (内存/磁盘/Redis)
│   │   ├── hls_proxy_service.py   # HLS代理服务（请求流水线）
│   │   ├── metadata_service.py    # metadata.txt 解析
│   │   └── segment_source.py      # 内容源抽象 (本地/网盘)
│   ├── upload.py                  # 上传 CLI（委托 BaiduYunService）
│   └── utils/
│       └── m3u8_parser.py         # M3U8解析/重写/生成
├── config/
│   └── settings.py            # 配置管理 (唯一配置源)
├── web/
│   ├── index.html             # 影库首页（变体 A）
│   ├── play.html              # 播放页（支持带 inline 详情 + metadata 回退）
│   ├── css/
│   │   ├── library.css        # 影库首页样式
│   │   └── play.css           # 播放页样式
│   └── js/
│       ├── library.js         # 影库首页逻辑
│       └── play.js            # 播放页逻辑
├── prototype/                 # 一次性原型，参考用，不要在生产用
│   ├── README.md
│   ├── home.html
│   ├── home.css
│   ├── home.js
│   └── catalog_proxy.py
├── vercel.json                # Vercel 部署配置
├── package.json               # Vercel CLI 脚本
├── requirements.txt           # 依赖包
├── .env.example              # 环境变量模板
└── start.sh                  # 启动脚本
```

## 快速开始

### 1. 安装依赖

```bash
# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置百度网盘

编辑 `.env` 文件，添加百度网盘 access_token：

```bash
ACCESS_TOKEN=xxxx
```
 
### 3. 启动服务

```bash
# 使用启动脚本
chmod +x start.sh
./start.sh

# 或直接运行
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. 使用服务

服务启动后，通过以下URL访问：

- **影库首页**: `http://localhost:8000/`（重定向到 `/web/`） 或 `http://localhost:8000/web/`
- **播放页**: `http://localhost:8000/web/play.html?path=<fan_code>`
- **健康检查**: `http://localhost:8000/health`
- **HLS代理**: `http://localhost:8000/hls/{网盘文件路径}`
- **目录 API 代理**: `http://localhost:8000/api/catalog/*`（前端 → 上游目录 API）

**示例**：
```bash
# 影库首页
http://localhost:8000/

# 播放网盘中的视频
http://localhost:8000/hls/video.m3u8

# 分片文件会自动代理
http://localhost:8000/hls/segment_0001.ts
```

## 影库 / 目录 API

`web/index.html` 是影库首页（变体 A：封面墙 + 顶部搜索 + 左栏 facets）。
页面通过 `/api/catalog/*` 拉取数据；该路由是后端代理，转发到由
`CATALOG_API_BASE` 配置的上游目录 API（默认 `http://127.0.0.1:8010`，
对应本地 demo 目录 API）。

- `/api/catalog/api/movies?page=&size=&labels=&q=` — 列表
- `/api/catalog/api/movies/{fan_code}` — 单部详情

上游 base 走 `settings.catalog_api_base`，不接受客户端覆盖。
如果设置了 `CATALOG_API_TOKEN`，转发时自动加 `Authorization: Bearer`。
请求上游的超时走 `settings.catalog_timeout`。

点击首页任一影片会跳到 `web/play.html?path=...`，把库里的详情（title /
cover / cast / tags / year / duration / description）通过 URL 参数带过去；
播放页直接渲染，不用等后端返回。只有 `?path=xxx` 这种老链接才会去
拉 `GET /metadata/{path}` 补 metadata。

外部 demo 目录 API 不支持 `q`（关键词搜索），所以搜索暂时退化为
「已加载数据的前端过滤」——搜索框占位符里也明示了这一点，`labels`
走服务端筛选。

> `prototype/` 目录里是早期的对比原型（3 个变体 / 旧版代理），保留作
> 参考，不要在生产用。详见 `prototype/README.md`。

## 网盘文件组织

在百度网盘中，HLS文件应按 `YUN_PATH_PREFIX`（默认 `/apps/movies`）组织：

```
/apps/movies/
├── video1.m3u8
├── video1/
│   ├── segment_0001.ts
│   ├── segment_0002.ts
│   └── ...
└── video2.m3u8
```

## 配置说明

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `ACCESS_TOKEN` | 百度网盘 access_token | - |
| `DEBUG` | 调试模式（同时控制是否开放 `/docs`） | `True` |
| `HOST` | 服务监听地址 | `0.0.0.0` |
| `PORT` | 服务监听端口 | `8000` |
| `CACHE_DIR` | 缓存目录 | `./cache` |
| `CACHE_TTL` | 缓存过期时间(秒) | `3600` |
| `CACHE_ENABLED` | 是否启用磁盘缓存（只读文件系统如 Vercel 设为 `false`） | `True` |
| `CACHE_SEGMENTS` | 是否缓存 HLS 分片文件 | `False` |
| `YUN_PATH_PREFIX` | 网盘 HLS 存储根路径（`/hls/{path}` 映射到 `<YUN_PATH_PREFIX>/{path}`） | `/apps/movies` |
| `LOCAL_PATH` | 本地 HLS 文件目录（存在则自动启用本地模式） | `./local_hls` |
| `REDIS_URL` / `REDIS_TOKEN` | Redis / Upstash (Vercel KV) 地址，用于跨实例存储 fsid | - |
| `CATALOG_API_BASE` | 影库首页代理的上游目录 API base | `http://127.0.0.1:8010` |
| `CATALOG_API_TOKEN` | 转发到上游时透传的 `Authorization: Bearer` token | - |
| `CATALOG_TIMEOUT` | 请求上游目录 API 的超时（秒） | `10.0` |

> `REDIS_URL` / `REDIS_TOKEN` 同时兼容 Vercel/Upstash 注入的变量名：
> `KV_REST_API_URL`/`KV_REST_API_TOKEN` 与 `UPSTASH_REDIS_REST_URL`/`UPSTASH_REDIS_REST_TOKEN`。
> 一旦配置了 Redis，fsid 将存入 Redis（不受 `CACHE_ENABLED` 影响）。

> **本地模式**：当 `LOCAL_PATH` 目录存在时自动启用，所有文件只从本地读取，缺失返回 404，不会回落到网盘（完全离线）。想回落到网盘就删除/改掉 `LOCAL_PATH`。

## 上传文件到网盘

```bash
# 上传单个文件（默认目标根为 YUN_PATH_PREFIX）
python -m app.upload video.ts --retries 5

# 上传目录（5 并发 + 断点续传）
python -m app.upload ./my_videos /apps/movies/my_videos -w 5

# 跳过超过 100MB 的文件、不续传、覆盖同名
python -m app.upload ./my_videos /apps/movies/my_videos --max-size 100MB --no-resume -o overwrite
```

上传逻辑（含重试）由 `BaiduYunService` 提供，CLI 只负责参数解析与进度展示。默认上传成功后删除本地文件，加 `--no-delete-after-upload` 保留。

## Vercel 部署

项目从**仓库根目录**部署到 Vercel，本地和 Vercel 运行的是同一个应用实例。

- 入口：`api/index.py`（`from app.main import app`，由 `@vercel/python` 直接托管 ASGI 应用）
- 配置：`vercel.json`（所有路径路由到 `/api/index`）
- 脚本：根目录 `package.json`（`vercel dev` / `vercel --prod`）

### 部署步骤

```bash
# 安装 Vercel CLI
npm i -g vercel

# 部署
vercel --prod
```

### 必需的环境变量（在 Vercel 后台配置）

```
ACCESS_TOKEN=<百度 token>
CACHE_ENABLED=false        # Vercel 文件系统只读（仅 /tmp 可写）
DEBUG=false
```

### fsid 存储（推荐）

Vercel 是无状态的，fsid 内存缓存在冷启动后会丢失。建议在
**Vercel Marketplace → Storage** 添加 **Upstash Redis** 集成，它会自动注入
`KV_REST_API_URL` / `KV_REST_API_TOKEN`，代码会自动识别并把 fsid 存入 Redis，
从而跨实例、跨冷启动共享，进一步减少百度网盘 API 调用。

fsid 存储后端按优先级自动选择：**Redis > 磁盘(`CACHE_ENABLED`) > 内存**。

## API端点

### GET /health
健康检查接口

**响应**:
```json
{
  "status": "ok",
  "service": "yunpan-hls-proxy",
  "message": "服务运行正常"
}
```

### GET /hls/{path:path}
HLS代理接口

**参数**:
- `path`: 网盘文件路径

**示例**:
```
GET /hls/video.m3u8
GET /hls/video/segment_0001.ts
```

## 性能优化

1. **本地缓存**: 减少网盘API调用
2. **异步处理**: 使用asyncio提升并发性能
3. **分块传输**: 支持大文件流式传输
4. **CORS支持**: 允许跨域请求

## 注意事项

1. **网盘限流**: 百度网盘可能有API调用频率限制
2. **access_token有效期**: access_token可能过期，需要定期更新
3. **带宽限制**: 免费账号可能有下载速度限制
4. **缓存空间**: 注意监控本地缓存大小
5. termux :
   ```shell
    pkg update
    pkg upgrade
    #因为需要rust来编译某些包
    pkg install clang rust make pkg-config
    pip install -U pip setuptools wheel 
    #指定当前的android版本
    export ANDROID_API_LEVEL=$(getprop ro.build.version.sdk)
  ```

## 待优化功能

- [ ] 支持更多网盘服务 (阿里云盘、天翼云盘)
- [ ] 缓存清理策略优化
- [ ] 监控和日志分析
- [ ] Docker支持
- [ ] 认证和权限控制

## License

MIT