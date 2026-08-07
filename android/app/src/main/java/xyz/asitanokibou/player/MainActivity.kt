package xyz.asitanokibou.player

import android.Manifest
import android.content.ComponentName
import android.content.pm.ActivityInfo
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.content.ContextCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.media3.common.Player
import androidx.media3.session.MediaController
import androidx.media3.session.SessionToken
import com.google.common.util.concurrent.ListenableFuture
import com.google.common.util.concurrent.MoreExecutors
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import xyz.asitanokibou.player.baidu.BaiduYunClient
import xyz.asitanokibou.player.config.AppSettings
import xyz.asitanokibou.player.service.PlaybackService
import xyz.asitanokibou.player.ui.AppRoot

class MainActivity : ComponentActivity() {

    private var controller by mutableStateOf<Player?>(null)
    private var controllerFuture: ListenableFuture<MediaController>? = null

    /** UI 侧独立的 BaiduYunClient：仅供列表页拉取 /apps/movies 目录用，与 PlaybackService 中的实例解耦 */
    private var baiduClient: BaiduYunClient? = null
    private val activityScope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    @Volatile private var currentToken: String? = null

    private val requestNotificationPermission =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { /* 结果不影响播放 */ }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        maybeRequestNotificationPermission()
        val settings = AppSettings(applicationContext)

        // 持续跟踪 token 变更，使列表页能始终用最新 token 调百度 API
        activityScope.launch {
            settings.configFlow.map { it.accessToken }.collect { currentToken = it }
        }
        val client = BaiduYunClient(tokenProvider = { currentToken })
        baiduClient = client

        setContent {
            AppRoot(
                controller = controller,
                settings = settings,
                baidu = client,
                onFullscreenChanged = { fullscreen -> applyFullscreen(fullscreen) },
            )
        }
    }

    /** Android 13+ 需运行时申请通知权限；拒绝不影响播放，仅影响通知栏控制 */
    private fun maybeRequestNotificationPermission() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        val granted = ContextCompat.checkSelfPermission(
            this, Manifest.permission.POST_NOTIFICATIONS
        ) == PackageManager.PERMISSION_GRANTED
        if (!granted) {
            requestNotificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    /**
     * 切换沉浸式全屏 + 横竖屏方向。
     * - 开启：隐藏状态栏与导航栏、强制横屏
     * - 关闭：恢复系统栏、解除方向锁定
     *
     * 必须与 AndroidManifest 中 `configChanges` 配合，避免横屏旋转时 Activity 被销毁。
     */
    private fun applyFullscreen(fullscreen: Boolean) {
        WindowCompat.setDecorFitsSystemWindows(window, !fullscreen)
        val insetsController = WindowInsetsControllerCompat(window, window.decorView)
        insetsController.systemBarsBehavior =
            WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        requestedOrientation = if (fullscreen) {
            insetsController.hide(WindowInsetsCompat.Type.systemBars())
            ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
        } else {
            insetsController.show(WindowInsetsCompat.Type.systemBars())
            ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
        }
    }

    override fun onStart() {
        super.onStart()
        val token = SessionToken(this, ComponentName(this, PlaybackService::class.java))
        val future = MediaController.Builder(this, token).buildAsync()
        controllerFuture = future
        future.addListener(
            {
                controller = try {
                    future.get()
                } catch (e: Exception) {
                    android.util.Log.e("MainActivity", "连接播放服务失败", e)
                    null
                }
            },
            MoreExecutors.directExecutor(),
        )
    }

    override fun onStop() {
        controllerFuture?.let { MediaController.releaseFuture(it) }
        controllerFuture = null
        controller = null
        super.onStop()
    }

    override fun onDestroy() {
        super.onDestroy()
        activityScope.cancel()
        baiduClient?.close()
        baiduClient = null
    }
}

