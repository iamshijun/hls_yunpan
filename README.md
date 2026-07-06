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
yunpan_hls/
├── app/
│   ├── main.py                 # 应用入口
│   ├── routes/
│   │   ├── hls.py             # HLS代理路由
│   │   └── health.py          # 健康检查
│   ├── services/
│   │   ├── baiduyun_service.py    # 百度网盘服务
│   │   ├── cache_service.py       # 缓存服务
│   │   └── hls_proxy_service.py   # HLS代理服务
│   └── utils/
│       └── m3u8_parser.py     # M3U8解析工具
├── config/
│   └── settings.py            # 配置管理
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

编辑 `.env` 文件，添加百度网盘ACCESS_TOKEN：

```bash
BAIDU_TOKEN=xxxx 
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

- **健康检查**: `http://localhost:8000/health`
- **HLS代理**: `http://localhost:8000/hls/{网盘文件路径}`

**示例**：
```bash
# 播放网盘中的视频
http://localhost:8000/hls/video.m3u8

# 分片文件会自动代理
http://localhost:8000/hls/segment_0001.ts
```

## 网盘文件组织

在百度网盘中，HLS文件应按以下结构组织：

```
/Apps/hls/
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
| `BAIDU_TOKEN` | 百度网盘access_token | - |
| `DEBUG` | 调试模式 | `True` |
| `HOST` | 服务监听地址 | `0.0.0.0` |
| `PORT` | 服务监听端口 | `8000` |
| `CACHE_DIR` | 缓存目录 | `./cache` |
| `CACHE_TTL` | 缓存过期时间(秒) | `3600` |

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

## 待优化功能

- [ ] 支持更多网盘服务 (阿里云盘、天翼云盘)
- [ ] 断点续传支持
- [ ] 缓存清理策略优化
- [ ] 监控和日志分析
- [ ] Docker支持
- [ ] 认证和权限控制

## License

MIT