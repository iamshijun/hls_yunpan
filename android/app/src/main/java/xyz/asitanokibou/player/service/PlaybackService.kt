package xyz.asitanokibou.player.service

import android.util.Log
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.session.MediaSession
import androidx.media3.session.MediaSessionService
import com.google.common.util.concurrent.Futures
import com.google.common.util.concurrent.ListenableFuture
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import xyz.asitanokibou.player.baidu.BaiduYunClient
import xyz.asitanokibou.player.cache.FileCache
import xyz.asitanokibou.player.cache.MemoryFsidStore
import xyz.asitanokibou.player.config.AppSettings
import xyz.asitanokibou.player.proxy.HlsProxyHandler
import xyz.asitanokibou.player.proxy.ProxyServer
import java.io.File

/**
 * 播放服务：统一托管 ExoPlayer + 本地 Ktor 代理。
 *
 * - onCreate 读取配置快照，构建 百度客户端 / 缓存 / fsid / 代理处理器，并启动本地代理拿到端口
 * - MediaSession.Callback 将控制端传入的 mediaId(用户输入的目录路径)解析为
 *   `http://127.0.0.1:<port>/hls/<path>/playlist.m3u8`
 * - 以 mediaPlayback 前台服务运行（Media3 自动管理前台通知与保活）
 *
 * 注意：access_token 通过 tokenProvider 动态读取，改 token 立即生效；
 * cacheEnabled/cacheSegments/ttl 在服务启动时快照，修改需重启服务生效（MVP）。
 */
class PlaybackService : MediaSessionService() {

    private lateinit var player: ExoPlayer
    private lateinit var mediaSession: MediaSession

    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    private var proxyServer: ProxyServer? = null
    private var baidu: BaiduYunClient? = null

    @Volatile private var currentToken: String? = null
    @Volatile private var port: Int = -1

    override fun onCreate() {
        super.onCreate()

        val settings = AppSettings(this)
        val config = runBlocking { settings.get() } // 启动时读取一次快照（小文件）
        currentToken = config.accessToken

        // 持续观察 token 变化，动态生效
        serviceScope.launch {
            settings.configFlow.map { it.accessToken }.collect { currentToken = it }
        }

        val client = BaiduYunClient(tokenProvider = { currentToken })
        baidu = client

        val ttlMillis = config.cacheTtlSec * 1000
        val fileCache = FileCache(
            cacheDir = File(cacheDir, "hls"),
            ttlMillis = ttlMillis,
            enabled = config.cacheEnabled,
        )
        val fsidStore = MemoryFsidStore(ttlMillis = ttlMillis)
        val handler = HlsProxyHandler(
            baidu = client,
            fileCache = fileCache,
            fsidStore = fsidStore,
            hlsRootPath = "/hls",
            cacheSegments = config.cacheSegments,
        )

        val server = ProxyServer(handler, preferredPort = config.port)
        port = server.start()
        proxyServer = server
        runningPort = port

        player = ExoPlayer.Builder(this)
            .setHandleAudioBecomingNoisy(true) // 拔耳机自动暂停
            .setWakeMode(C.WAKE_MODE_NETWORK)  // 播放时保持 CPU+网络唤醒
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setContentType(C.AUDIO_CONTENT_TYPE_MOVIE)
                    .setUsage(C.USAGE_MEDIA)
                    .build(),
                /* handleAudioFocus = */ true,
            )
            .build()
        mediaSession = MediaSession.Builder(this, player)
            .setCallback(MediaSessionCallback())
            .build()

        Log.i(TAG, "PlaybackService 已就绪，代理端口=$port")
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaSession = mediaSession

    /** 用户从最近任务中滑掉应用：未在播放则停止服务，节省资源 */
    override fun onTaskRemoved(rootIntent: android.content.Intent?) {
        if (!player.playWhenReady || player.mediaItemCount == 0) {
            stopSelf()
        }
        super.onTaskRemoved(rootIntent)
    }

    override fun onDestroy() {
        mediaSession.release()
        player.release()
        proxyServer?.stop()
        baidu?.close()
        runningPort = -1
        serviceScope.cancel()
        super.onDestroy()
    }

    /** 将 mediaId(用户输入的目录路径)解析为本地代理的 m3u8 URL */
    private inner class MediaSessionCallback : MediaSession.Callback {
        override fun onAddMediaItems(
            mediaSession: MediaSession,
            controller: MediaSession.ControllerInfo,
            mediaItems: MutableList<MediaItem>,
        ): ListenableFuture<MutableList<MediaItem>> {
            val resolved = mediaItems.map { item ->
                val uri = buildPlaylistUri(item.mediaId)
                item.buildUpon().setUri(uri).build()
            }.toMutableList()
            return Futures.immediateFuture(resolved)
        }
    }

    private fun buildPlaylistUri(mediaId: String): String {
        val clean = mediaId.trim().trimStart('/')
        return "http://127.0.0.1:$port/hls/$clean/playlist.m3u8"
    }

    companion object {
        private const val TAG = "PlaybackService"

        /** 供 UI 展示/调试的当前端口，-1 表示未运行 */
        @Volatile
        var runningPort: Int = -1
            private set
    }
}
