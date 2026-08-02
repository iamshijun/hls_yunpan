package xyz.asitanokibou.player.baidu

import android.util.Log
import io.ktor.client.HttpClient
import io.ktor.client.call.body
import io.ktor.client.engine.okhttp.OkHttp
import io.ktor.client.plugins.HttpTimeout
import io.ktor.client.request.get
import io.ktor.client.request.header
import io.ktor.client.request.parameter
import io.ktor.client.request.prepareGet
import io.ktor.client.statement.bodyAsChannel
import io.ktor.client.statement.bodyAsText
import io.ktor.http.HttpHeaders
import io.ktor.utils.io.ByteReadChannel
import kotlinx.serialization.json.Json
import xyz.asitanokibou.player.baidu.model.BaiduFile
import xyz.asitanokibou.player.baidu.model.FileListResponse
import xyz.asitanokibou.player.baidu.model.FileMetasResponse

/** 百度 API 调用异常 */
class BaiduApiException(message: String) : Exception(message)

/**
 * 百度网盘客户端（对齐 Python `baiduyun_service.py`）。
 *
 * - 列表 / 元数据用浏览器 UA
 * - 下载直链必须用 `User-Agent: pan.baidu.com` 且携带 access_token、跟随重定向
 * - errno != 0 视为业务失败
 *
 * @param tokenProvider 返回当前 access_token（来源于设置，可动态变化）
 */
class BaiduYunClient(
    private val tokenProvider: () -> String?,
) {
    private val json = Json {
        ignoreUnknownKeys = true
        isLenient = true
    }

    private val http: HttpClient = HttpClient(OkHttp) {
        // OkHttp 引擎：完整实现 hostname-aware checkServerTrusted，
        // 避免 Android 7+ 在严格 networkSecurityConfig 下抛 CertificateException
        followRedirects = true
        expectSuccess = true // 类似 httpx 的 raise_for_status（HTTP 层）
        install(HttpTimeout) {
            connectTimeoutMillis = API_TIMEOUT_MS
            requestTimeoutMillis = DOWNLOAD_STREAM_TIMEOUT_MS
            socketTimeoutMillis = DOWNLOAD_STREAM_TIMEOUT_MS
        }
    }

    /** 获取目录下所有文件（分批，batch=1000） */
    suspend fun getFileListAll(path: String = "/"): List<BaiduFile> {
        val all = mutableListOf<BaiduFile>()
        var start = 0
        while (true) {
            val files = getFileList(path, start, BATCH_SIZE)
            if (files.isEmpty()) break
            all.addAll(files)
            if (files.size < BATCH_SIZE) break
            start += BATCH_SIZE
            Log.i(TAG, "已获取 ${all.size} 个文件，继续获取...")
        }
        Log.i(TAG, "目录 [$path] 共有 ${all.size} 个文件")
        return all
    }

    /** 获取目录下的文件列表（单批） */
    private suspend fun getFileList(path: String = "/", start: Int = 0, limit: Int = BATCH_SIZE): List<BaiduFile> {
        val token = requireToken()
        val text = http.get(LIST_URL) {
            parameter("method", "list")
            parameter("dir", path)
            parameter("order", "name")
            parameter("start", start)
            parameter("limit", limit)
            parameter("access_token", token)
            header(HttpHeaders.UserAgent, WEB_UA)
        }.bodyAsText()

        val resp = json.decodeFromString<FileListResponse>(text)
        if (resp.errno != 0) {
            Log.e(TAG, "获取文件列表失败: errno=${resp.errno} ${resp.errmsg}")
            return emptyList()
        }
        return resp.list
    }

    /** 通过 fsid 获取下载直链 */
    private suspend fun getDownloadUrl(fsid: Long): String {
        val token = requireToken()
        val text = http.get(META_URL) {
            parameter("method", "filemetas")
            parameter("access_token", token)
            parameter("dlink", 1)
            parameter("fsids", "[$fsid]")
            header(HttpHeaders.UserAgent, WEB_UA)
        }.bodyAsText()

        val resp = json.decodeFromString<FileMetasResponse>(text)
        if (resp.errno != 0) {
            throw BaiduApiException("获取下载链接失败: errno=${resp.errno} ${resp.errmsg}")
        }
        return resp.list.firstOrNull()?.dlink
            ?: throw BaiduApiException("下载链接为空 (fsid=$fsid)")
    }

    /** 下载整个文件（用于较小的 m3u8） */
    suspend fun downloadBytes(fsid: Long): ByteArray {
        val dlink = getDownloadUrl(fsid)
        Log.i(TAG, "download fsid=$fsid dlink=$dlink")
        return http.get(dlink) {
            parameter("access_token", requireToken())
            header(HttpHeaders.UserAgent, DOWNLOAD_UA)
        }.body()
    }

    /**
     * 流式下载文件。字节流仅在 [block] 内有效（Ktor 流式生命周期）。
     * 供代理层将其复制到本地响应，避免整包缓冲。
     */
    suspend fun <T> openDownloadStream(fsid: Long, block: suspend (ByteReadChannel) -> T): T {
        val dlink = getDownloadUrl(fsid)
        return http.prepareGet(dlink) {
            parameter("access_token", requireToken())
            header(HttpHeaders.UserAgent, DOWNLOAD_UA)
        }.execute { response ->
            block(response.bodyAsChannel())
        }
    }

    fun close() {
        http.close()
    }

    private fun requireToken(): String =
        tokenProvider()?.takeIf { it.isNotBlank() }
            ?: throw BaiduApiException("未配置 access_token")

    companion object {
        private const val TAG = "BaiduYunClient"
        const val BATCH_SIZE = 1000

        private const val API_TIMEOUT_MS = 30_000L
        private const val DOWNLOAD_STREAM_TIMEOUT_MS = 300_000L

        private const val WEB_UA =
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        private const val DOWNLOAD_UA = "pan.baidu.com"

        private const val LIST_URL = "https://pan.baidu.com/rest/2.0/xpan/file"
        private const val META_URL = "https://pan.baidu.com/rest/2.0/xpan/multimedia"
    }
}
