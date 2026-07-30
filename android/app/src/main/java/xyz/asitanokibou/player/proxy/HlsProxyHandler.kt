package xyz.asitanokibou.player.proxy

import android.util.Log
import io.ktor.http.ContentType
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.server.application.ApplicationCall
import io.ktor.server.request.header
import io.ktor.server.response.respondBytes
import io.ktor.server.response.respondBytesWriter
import io.ktor.server.response.respondText
import io.ktor.utils.io.writeFully
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import xyz.asitanokibou.player.baidu.BaiduYunClient
import xyz.asitanokibou.player.cache.FileCache
import xyz.asitanokibou.player.cache.FsidStore
import java.io.ByteArrayOutputStream
import java.util.concurrent.ConcurrentHashMap

/**
 * HLS 代理核心处理器（对齐 Python `hls_proxy_service.py`）。
 *
 * 直接基于 Ktor [ApplicationCall] 应答，支持 m3u8 改写与分片流式转发。
 * 说明：Android 版 MVP 不含 local_mode（本地文件夹播放留待后续）。
 */
class HlsProxyHandler(
    private val baidu: BaiduYunClient,
    private val fileCache: FileCache,
    private val fsidStore: FsidStore,
    private val hlsRootPath: String = "/hls",
    private val cacheSegments: Boolean = false,
) {
    private val dirLocks = ConcurrentHashMap<String, Mutex>()

    /** 路由入口：按后缀 / Accept 头分派（对齐 routes/hls.py） */
    suspend fun handle(call: ApplicationCall, path: String) {
        val requestPath = "$hlsRootPath/$path"
        when {
            path.endsWith(".m3u8") -> handleM3u8(call, requestPath)
            path.endsWith(".ts") -> handleChunk(call, requestPath)
            else -> {
                val accept = call.request.header(HttpHeaders.Accept) ?: ""
                if (accept.contains("m3u8") || accept.contains("mpegurl")) {
                    handleM3u8(call, requestPath)
                } else {
                    handleChunk(call, requestPath)
                }
            }
        }
    }

    private suspend fun handleM3u8(call: ApplicationCall, requestPath: String) {
        try {
            val yunPath = convertToYunPath(requestPath)
            val dirPath = dirName(yunPath)
            Log.i(TAG, "处理m3u8请求: $requestPath -> $yunPath")

            var content = fileCache.get(yunPath)
            if (content == null) {
                // 首次访问：加载目录下所有文件的 fsid
                loadDirectoryFsids(dirPath)
                val fsid = fsidStore.get(yunPath)
                if (fsid == null) {
                    Log.e(TAG, "未找到文件的fsid: $yunPath")
                    call.respondText("File not found: $yunPath", status = HttpStatusCode.NotFound)
                    return
                }
                content = baidu.downloadBytes(fsid)
                fileCache.set(yunPath, content)
            }

            val rewritten = M3u8Rewriter.rewrite(content, requestPath)
            call.response.headers.append(HttpHeaders.CacheControl, "public, max-age=3600")
            call.response.headers.append(HttpHeaders.AccessControlAllowOrigin, "*")
            call.respondBytes(rewritten, M3U8_CONTENT_TYPE, HttpStatusCode.OK)
        } catch (e: Exception) {
            Log.e(TAG, "处理m3u8请求失败: $e")
            call.respondText("Error: ${e.message}", status = HttpStatusCode.InternalServerError)
        }
    }

    private suspend fun handleChunk(call: ApplicationCall, requestPath: String) {
        val yunPath = convertToYunPath(requestPath)
        val dirPath = dirName(yunPath)
        Log.i(TAG, "处理分片请求: $requestPath -> $yunPath")

        // 命中缓存直接返回（即使 cacheSegments 关闭，命中也用缓存以减少 API 调用）
        val fsid: Long
        try {
            val cached = fileCache.get(yunPath)
            if (cached != null) {
                appendChunkHeaders(call)
                call.respondBytes(cached, TS_CONTENT_TYPE, HttpStatusCode.OK)
                return
            }

            var id = fsidStore.get(yunPath)
            if (id == null) {
                Log.w(TAG, "分片文件fsid未缓存，尝试加载目录: $dirPath")
                loadDirectoryFsids(dirPath)
                id = fsidStore.get(yunPath)
            }
            if (id == null) {
                Log.e(TAG, "未找到分片文件的fsid: $yunPath")
                call.respondText("File not found: $yunPath", status = HttpStatusCode.NotFound)
                return
            }
            fsid = id
        } catch (e: Exception) {
            Log.e(TAG, "分片请求预处理失败: $e")
            call.respondText("Error: ${e.message}", status = HttpStatusCode.InternalServerError)
            return
        }

        // 流式转发（头部一旦提交无法再改状态码；流中异常仅记录）
        appendChunkHeaders(call)
        call.respondBytesWriter(contentType = TS_CONTENT_TYPE) {
            try {
                val buffered = if (cacheSegments) ByteArrayOutputStream() else null
                baidu.openDownloadStream(fsid) { source ->
                    val buf = ByteArray(BUFFER_SIZE)
                    while (true) {
                        val n = source.readAvailable(buf, 0, buf.size)
                        if (n == -1) break
                        if (n > 0) {
                            writeFully(buf, 0, n)
                            buffered?.write(buf, 0, n)
                        }
                    }
                }
                // 全部发送完成后再写缓存（仅在启用分片缓存时）
                buffered?.let { fileCache.set(yunPath, it.toByteArray()) }
            } catch (e: Exception) {
                Log.e(TAG, "分片流式转发失败 [$yunPath]: $e")
            }
        }
    }

    private fun appendChunkHeaders(call: ApplicationCall) {
        val cacheControl = if (cacheSegments) "public, max-age=86400" else "no-cache"
        call.response.headers.append(HttpHeaders.CacheControl, cacheControl)
        call.response.headers.append(HttpHeaders.AccessControlAllowOrigin, "*")
    }

    /** 加载目录下所有文件的 fsid 并缓存（按目录加锁，避免并发重复拉取） */
    private suspend fun loadDirectoryFsids(dirPath: String) {
        val lock = dirLocks.getOrPut(dirPath) { Mutex() }
        lock.withLock {
            Log.i(TAG, "开始加载目录 [$dirPath] 的文件列表和fsid...")
            val files = baidu.getFileListAll(dirPath)
            val map = HashMap<String, Long>(files.size)
            for (f in files) {
                if (f.path.isNotEmpty() && f.fsId != 0L) {
                    map[f.path] = f.fsId
                }
            }
            fsidStore.setMany(map)
            Log.i(TAG, "目录 [$dirPath] 加载完成，共 ${map.size} 个文件")
        }
    }

    /** 请求路径转网盘路径（对齐 _convert_to_yun_path） */
    private fun convertToYunPath(requestPath: String): String {
        var p = requestPath
        if (p.startsWith(hlsRootPath)) {
            p = p.substring(hlsRootPath.length)
        }
        return "/apps/movies$p"
    }

    /** 取父目录（对齐 os.path.dirname(...) or "/"） */
    private fun dirName(path: String): String {
        val idx = path.lastIndexOf('/')
        return if (idx <= 0) "/" else path.substring(0, idx)
    }

    companion object {
        private const val TAG = "HlsProxyHandler"
        private const val BUFFER_SIZE = 65536
        private val M3U8_CONTENT_TYPE = ContentType("application", "vnd.apple.mpegurl")
        private val TS_CONTENT_TYPE = ContentType("video", "mp2t")
    }
}
