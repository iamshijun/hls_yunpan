package xyz.asitanokibou.player.proxy

import android.util.Log
import io.ktor.http.ContentType
import io.ktor.server.application.Application
import io.ktor.server.application.call
import io.ktor.server.cio.CIO
import io.ktor.server.engine.ApplicationEngine
import io.ktor.server.engine.embeddedServer
import io.ktor.server.response.respondText
import io.ktor.server.routing.get
import io.ktor.server.routing.routing
import java.net.ServerSocket

/**
 * 本地 HLS 代理服务（对齐 Python `app/main.py` 的路由部分）。
 *
 * 仅监听 127.0.0.1；`port=0` 时自动选择空闲端口。
 * 路由：
 *  - GET /health
 *  - GET /hls/{path...}  → 交给 [HlsProxyHandler]
 */
class ProxyServer(
    private val handler: HlsProxyHandler,
    private val preferredPort: Int = 0,
) {
    private var engine: ApplicationEngine? = null

    var port: Int = -1
        private set

    /** 启动服务（非阻塞），返回实际监听端口 */
    fun start(): Int {
        if (engine != null) return port

        val chosen = if (preferredPort > 0) preferredPort else findFreePort()
        val srv = embeddedServer(CIO, host = HOST, port = chosen) {
            // 给大目录 fsid 加载 + m3u8 下载留足时间（默认 15s 太短）

            configureRouting()
        }
        srv.start(wait = false)
        engine = srv
        port = chosen
        Log.i(TAG, "本地代理已启动: http://$HOST:$chosen")
        return chosen
    }

    fun stop() {
        engine?.stop(GRACE_MILLIS, TIMEOUT_MILLIS)
        engine = null
        port = -1
    }

    private fun Application.configureRouting() {
        routing {
            get("/health") {
                call.respondText(
                    """{"status":"ok","service":"hls_pan_player"}""",
                    ContentType.Application.Json,
                )
            }
            get("/hls/{path...}") {
                val segments = call.parameters.getAll("path") ?: emptyList()
                val path = segments.joinToString("/")
                handler.handle(call, path)
            }
        }
    }

    private fun findFreePort(): Int = ServerSocket(0).use { it.localPort }

    companion object {
        private const val TAG = "ProxyServer"
        private const val HOST = "127.0.0.1"
        private const val GRACE_MILLIS = 500L
        private const val TIMEOUT_MILLIS = 1500L
        /** 单请求整体超时：兜住大目录 fsid 拉取 + m3u8 下载（分片用 respondBytesWriter 不受此限） */
        private const val SERVER_REQUEST_TIMEOUT_MS = 90_000L
    }
}
