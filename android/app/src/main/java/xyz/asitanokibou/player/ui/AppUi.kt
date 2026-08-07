package xyz.asitanokibou.player.ui

import android.app.Activity
import android.content.Context
import android.media.AudioManager
import androidx.activity.compose.BackHandler
import androidx.annotation.OptIn
import androidx.compose.foundation.background
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.ui.AspectRatioFrameLayout
import kotlinx.coroutines.launch
import xyz.asitanokibou.player.baidu.BaiduYunClient
import xyz.asitanokibou.player.config.AppConfig
import xyz.asitanokibou.player.config.AppSettings
import kotlin.math.abs
import kotlin.math.roundToInt

@Composable
fun AppRoot(
    controller: Player?,
    settings: AppSettings,
    baidu: BaiduYunClient? = null,
    onFullscreenChanged: (Boolean) -> Unit = {},
) {
    val nav = rememberNavState()
    val scope = rememberCoroutineScope()
    val config by settings.configFlow.collectAsState(initial = AppConfig())
    val hasToken = !config.accessToken.isNullOrBlank()
    // 不传 colorScheme 时 MaterialTheme 默认固定为浅色调色板，
    // 系统深色模式下输入框会出现“白字白底”不可见。显式按系统主题切换。
    val colorScheme = if (isSystemInDarkTheme()) darkColorScheme() else lightColorScheme()

    // 系统返回键：非首页时弹栈，首页时交由系统（关闭 Activity）
    BackHandler(enabled = nav.canPop) {
        nav.pop()
    }

    MaterialTheme(colorScheme = colorScheme) {
        when (val screen = nav.current) {
            is Screen.Index -> IndexScreen(
                onOpenList = { nav.push(Screen.MovieList) },
                onOpenDirect = { nav.push(Screen.Play(initialPath = "")) },
                onOpenSettings = { nav.push(Screen.Settings) },
            )
            is Screen.MovieList -> MovieListScreen(
                baidu = baidu,
                hasToken = hasToken,
                onBack = { nav.pop() },
                onPick = { relativePath -> nav.push(Screen.Play(initialPath = relativePath)) },
            )
            is Screen.Play -> HomeScreen(
                controller = controller,
                hasToken = hasToken,
                initialPath = screen.initialPath,
                onBack = { nav.pop() },
                onOpenSettings = { nav.push(Screen.Settings) },
                onFullscreenChanged = onFullscreenChanged,
            )
            is Screen.Settings -> SettingsScreen(
                initialToken = config.accessToken ?: "",
                initialCacheSegments = config.cacheSegments,
                onSave = { token, cacheSegments ->
                    scope.launch {
                        settings.update(
                            config.copy(accessToken = token, cacheSegments = cacheSegments)
                        )
                    }
                    nav.pop()
                },
                onBack = { nav.pop() },
            )
        }
    }
}

@OptIn(UnstableApi::class)
@Composable
private fun HomeScreen(
    controller: Player?,
    hasToken: Boolean,
    initialPath: String,
    onBack: () -> Unit,
    onOpenSettings: () -> Unit,
    onFullscreenChanged: (Boolean) -> Unit,
) {
    // 用 initialPath 作为 key 的一部分：列表点进来时用目录名初始化；点 "直接输入" 时为空
    var path by remember(initialPath) { mutableStateOf(initialPath) }
    val status = remember { mutableStateOf<String?>(null) }
    val error = remember { mutableStateOf<String?>(null) }
    var isFullscreen by remember { mutableStateOf(false) }

    // 把全屏状态同步给 Activity（用于隐藏系统栏 + 切换横屏）
    LaunchedEffect(isFullscreen) {
        onFullscreenChanged(isFullscreen)
    }

    // 全屏下用系统返回键退出
    BackHandler(enabled = isFullscreen) {
        isFullscreen = false
    }

    DisposableEffect(controller) {
        val listener = object : Player.Listener {
            override fun onPlaybackStateChanged(state: Int) {
                status.value = when (state) {
                    Player.STATE_IDLE -> "空闲"
                    Player.STATE_BUFFERING -> "缓冲中…"
                    Player.STATE_READY -> "就绪"
                    Player.STATE_ENDED -> "已结束"
                    else -> null
                }
            }
            override fun onPlayerError(error0: androidx.media3.common.PlaybackException) {
                error.value = "${error0.errorCodeName}: ${error0.message ?: ""}"
            }
        }
        controller?.addListener(listener)
        onDispose {
            controller?.removeListener(listener)
            // 离开播放页（点击"返回"/系统返回键/切到设置页）时先暂停 player：
            // 暂停会让解码器立即停止推帧，而 setVideoSurface(null) 是异步 IPC，
            // 若在 view/surface 销毁前仍有帧在推，就会触发 BLAST BufferQueue 死锁
            //（waitForFreeSlotThenRelock TIMED_OUT）。先 pause 让 IPC 抢在 surface
            // 销毁前到达 PlaybackService。
            controller?.pause()
        }
    }

    if (isFullscreen) {
        // 全屏态：仅显示 PlayerView，铺满屏幕（黑底避免画面变化时的白边）
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(Color.Black),
            contentAlignment = Alignment.Center,
        ) {
            HlsPlayerView(
                controller = controller,
                onToggleFullscreen = { isFullscreen = !isFullscreen },
                modifier = Modifier.fillMaxSize(),
                resizeMode = AspectRatioFrameLayout.RESIZE_MODE_FIT,
            )
        }
    } else {
        Scaffold(modifier = Modifier.fillMaxSize()) { innerPadding ->
            BoxWithConstraints(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(innerPadding),
            ) {
                // 平板/手机横屏时 maxWidth > maxHeight：改用 Row 布局把控件放左侧、播放器放右侧，
                // 避免 16:9 播放器在宽屏下占据绝大部分高度、把输入框挤出可见区域。
                val isWide = maxWidth > maxHeight

                if (isWide) {
                    Row(
                        modifier = Modifier
                            .fillMaxSize()
                            .padding(16.dp),
                        horizontalArrangement = Arrangement.spacedBy(16.dp),
                    ) {
                        ControlsPanel(
                            modifier = Modifier
                                .weight(1f)
                                .fillMaxHeight()
                                .verticalScroll(rememberScrollState()),
                            path = path,
                            onPathChange = { path = it },
                            onPlay = {
                                error.value = null
                                controller?.let { playPath(it, path) }
                            },
                            onBack = onBack,
                            onOpenSettings = onOpenSettings,
                            hasToken = hasToken,
                            controller = controller,
                            status = status.value,
                            error = error.value,
                        )
                        Box(
                            modifier = Modifier
                                .weight(1.4f)
                                .fillMaxHeight(),
                            contentAlignment = Alignment.Center,
                        ) {
                            HlsPlayerView(
                                controller = controller,
                                onToggleFullscreen = { isFullscreen = !isFullscreen },
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .aspectRatio(16f / 9f),
                                resizeMode = AspectRatioFrameLayout.RESIZE_MODE_FIT,
                            )
                        }
                    }
                } else {
                    Column(
                        modifier = Modifier.padding(16.dp),
                        verticalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        ControlsPanel(
                            modifier = Modifier.fillMaxWidth(),
                            path = path,
                            onPathChange = { path = it },
                            onPlay = {
                                error.value = null
                                controller?.let { playPath(it, path) }
                            },
                            onBack = onBack,
                            onOpenSettings = onOpenSettings,
                            hasToken = hasToken,
                            controller = controller,
                            status = status.value,
                            error = error.value,
                        )
                        Spacer(Modifier.padding(4.dp))
                        HlsPlayerView(
                            controller = controller,
                            onToggleFullscreen = { isFullscreen = !isFullscreen },
                            modifier = Modifier
                                .fillMaxWidth()
                                .aspectRatio(16f / 9f),
                            resizeMode = AspectRatioFrameLayout.RESIZE_MODE_FIT,
                        )
                    }
                }
            }
        }
    }
}

/**
 * 控件面板：标题行 + 路径输入 + 播放按钮 + 状态/错误提示。
 * 横屏布局里作为左侧列使用（外层已加 verticalScroll），竖屏布局里作为顶部列使用。
 */
@Composable
private fun ControlsPanel(
    modifier: Modifier = Modifier,
    path: String,
    onPathChange: (String) -> Unit,
    onPlay: () -> Unit,
    onBack: () -> Unit,
    onOpenSettings: () -> Unit,
    hasToken: Boolean,
    controller: Player?,
    status: String?,
    error: String?,
) {
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                TextButton(onClick = onBack) { Text("← 返回") }
                Spacer(Modifier.width(8.dp))
                Text("hls_pan_player", style = MaterialTheme.typography.titleLarge)
            }
            TextButton(onClick = onOpenSettings) { Text("设置") }
        }

        OutlinedTextField(
            value = path,
            onValueChange = onPathChange,
            label = { Text("媒体目录路径，例如 video1 或 movies/我的视频") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )

        Button(
            onClick = onPlay,
            enabled = controller != null && path.isNotBlank(),
        ) {
            Text("播放")
        }

        if (!hasToken) {
            Text(
                "请先在「设置」中填写百度网盘 access_token",
                color = MaterialTheme.colorScheme.error,
            )
        }
        if (controller == null) {
            Text("正在连接播放服务...", color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        status?.let {
            Text("状态：$it", color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        error?.let {
            Text("播放错误：$it", color = MaterialTheme.colorScheme.error)
        }
    }
}

/**
 * 包装手势版 PlayerView（GesturePlayerView），开启全屏按钮并把点击事件抛回 Compose 侧。
 * 同时负责接入手势回调、显示 seek/音量/亮度浮层。
 * 切到全屏时由调用方切换外层布局与系统栏/方向。
 *
 * 注：Media3 1.3.x 没有 setShowFullscreenButton API；只要设置了
 * FullscreenButtonClickListener，控制器就会自动展示全屏按钮。
 */
@OptIn(UnstableApi::class)
@Composable
private fun HlsPlayerView(
    controller: Player?,
    onToggleFullscreen: () -> Unit,
    modifier: Modifier = Modifier,
    resizeMode: Int = AspectRatioFrameLayout.RESIZE_MODE_FIT,
) {
    val context = LocalContext.current
    val audioManager = remember { context.getSystemService(Context.AUDIO_SERVICE) as AudioManager }

    var seekDeltaSec by remember { mutableStateOf<Float?>(null) }
    var seekBaseMs by remember { mutableStateOf(0L) }
    var volumeLevel by remember { mutableStateOf<Float?>(null) }
    var brightnessLevel by remember { mutableStateOf<Float?>(null) }
    var volumeBase by remember { mutableStateOf(0.5f) }
    var brightnessBase by remember { mutableStateOf(0.5f) }

    Box(modifier = modifier) {
        AndroidView(
            factory = { ctx ->
                GesturePlayerView(ctx).apply {
                    useController = true
                    this.resizeMode = resizeMode
                    setFullscreenButtonClickListener { onToggleFullscreen() }

                    onSeekPreview = { deltaSec ->
                        // 第一次预览时记录手势起点，保证松手跳转目标基于手势开始位置
                        if (seekDeltaSec == null) {
                            seekBaseMs = player?.currentPosition ?: 0L
                        }
                        seekDeltaSec = deltaSec
                    }
                    onSeekCommit = {
                        seekDeltaSec?.let { delta ->
                            val target = seekBaseMs + (delta * 1000).toLong()
                            player?.seekTo(target.coerceAtLeast(0L))
                        }
                        seekDeltaSec = null
                    }
                    onSeekCancel = {
                        seekDeltaSec = null
                    }
                    onVerticalDrag = { fraction, isLeftHalf ->
                        if (isLeftHalf) {
                            // 左半屏竖滑 → 亮度：首次回调记录手势起点亮度，之后按累计偏移计算
                            if (brightnessLevel == null) brightnessBase = readBrightness(context)
                            val target = (brightnessBase + fraction).coerceIn(0.01f, 1f)
                            setBrightness(context, target)
                            brightnessLevel = target
                        } else {
                            // 右半屏竖滑 → 音量：同样基于手势起点音量
                            val max = audioManager.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
                            if (volumeLevel == null && max > 0) {
                                volumeBase = audioManager.getStreamVolume(AudioManager.STREAM_MUSIC).toFloat() / max
                            }
                            val level = (volumeBase + fraction).coerceIn(0f, 1f)
                            if (max > 0) {
                                audioManager.setStreamVolume(
                                    AudioManager.STREAM_MUSIC,
                                    (level * max).roundToInt(),
                                    0,
                                )
                            }
                            volumeLevel = level
                        }
                    }
                    onVerticalDragEnd = {
                        volumeLevel = null
                        brightnessLevel = null
                    }
                    onDoubleTap = { side ->
                        player?.let { p ->
                            p.seekTo((p.currentPosition + side * DOUBLE_TAP_SEEK_MS).coerceAtLeast(0L))
                        }
                    }
                }
            },
            update = { view ->
                // 只在 view 已 attach 到窗口时才绑定 player：
                // 避免 SurfaceView 还没 layout 时解码器就往 0 尺寸的 surface 推帧，
                // 触发 BLAST BufferQueue 死锁（waitForFreeSlotThenRelock TIMED_OUT）。
                if (view.player !== controller) {
                    if (view.isAttachedToWindow) {
                        view.player = controller
                    } else {
                        view.post { view.player = controller }
                    }
                }
                view.resizeMode = resizeMode
            },
            onRelease = { view ->
                // 离开组合时清空 player 引用，避免 PlayerView 持有 MediaController 造成泄漏
                view.player = null
            },
            modifier = Modifier.matchParentSize(),
        )

        PlayerGestureOverlay(
            seekDeltaSec = seekDeltaSec,
            seekBaseMs = seekBaseMs,
            durationMs = controller?.duration?.takeIf { it > 0 } ?: 0L,
            volumeLevel = volumeLevel,
            brightnessLevel = brightnessLevel,
            modifier = Modifier.fillMaxSize(),
        )
    }
}

/** 手势过程中的浮层：中央显示 seek 预览，左右侧显示亮度/音量 */
@Composable
private fun PlayerGestureOverlay(
    seekDeltaSec: Float?,
    seekBaseMs: Long,
    durationMs: Long,
    volumeLevel: Float?,
    brightnessLevel: Float?,
    modifier: Modifier = Modifier,
) {
    Box(modifier = modifier, contentAlignment = Alignment.Center) {
        seekDeltaSec?.let { delta ->
            val targetMs = if (durationMs > 0) {
                (seekBaseMs + (delta * 1000).toLong()).coerceIn(0L, durationMs)
            } else {
                (seekBaseMs + (delta * 1000).toLong()).coerceAtLeast(0L)
            }
            SeekOverlay(
                deltaSec = delta,
                baseMs = seekBaseMs,
                targetMs = targetMs,
            )
        }
        brightnessLevel?.let { level ->
            LevelOverlay(
                label = "亮度",
                level = level,
                modifier = Modifier
                    .align(Alignment.CenterStart)
                    .padding(start = 28.dp),
            )
        }
        volumeLevel?.let { level ->
            LevelOverlay(
                label = "音量",
                level = level,
                modifier = Modifier
                    .align(Alignment.CenterEnd)
                    .padding(end = 28.dp),
            )
        }
    }
}

@Composable
private fun SeekOverlay(deltaSec: Float, baseMs: Long, targetMs: Long) {
    val isForward = deltaSec >= 0f
    Column(
        modifier = Modifier
            .background(Color.Black.copy(alpha = 0.65f), RoundedCornerShape(12.dp))
            .padding(horizontal = 24.dp, vertical = 16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            text = if (isForward) "快进 ${abs(deltaSec).roundToInt()} 秒" else "快退 ${abs(deltaSec).roundToInt()} 秒",
            color = Color.White,
            style = MaterialTheme.typography.titleLarge,
        )
        Spacer(Modifier.height(6.dp))
        Text(
            text = "${formatTime(baseMs)} → ${formatTime(targetMs)}",
            color = Color.White.copy(alpha = 0.85f),
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}

@Composable
private fun LevelOverlay(label: String, level: Float, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier
            .background(Color.Black.copy(alpha = 0.65f), RoundedCornerShape(10.dp))
            .padding(horizontal = 16.dp, vertical = 12.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(label, color = Color.White, style = MaterialTheme.typography.titleSmall)
        Spacer(Modifier.height(8.dp))
        // 垂直刻度条：从底部向上填充，贴合竖滑方向
        Box(
            modifier = Modifier
                .width(6.dp)
                .height(80.dp)
                .background(Color.White.copy(alpha = 0.3f), RoundedCornerShape(3.dp)),
            contentAlignment = Alignment.BottomCenter,
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .fillMaxHeight(level.coerceIn(0f, 1f))
                    .background(Color.White, RoundedCornerShape(3.dp)),
            )
        }
    }
}

private fun formatTime(ms: Long): String {
    val totalSec = ms / 1000
    val hours = totalSec / 3600
    val minutes = (totalSec % 3600) / 60
    val seconds = totalSec % 60
    return if (hours > 0) {
        String.format("%d:%02d:%02d", hours, minutes, seconds)
    } else {
        String.format("%02d:%02d", minutes, seconds)
    }
}

private fun readBrightness(context: Context): Float {
    val window = (context as? Activity)?.window ?: return 0.5f
    return if (window.attributes.screenBrightness >= 0f) {
        window.attributes.screenBrightness
    } else {
        0.5f // 跟随系统亮度时无从读取，用中间值作为起点
    }
}

private fun setBrightness(context: Context, value: Float) {
    val window = (context as? Activity)?.window ?: return
    val attrs = window.attributes
    attrs.screenBrightness = value.coerceIn(0.01f, 1f)
    window.attributes = attrs
}

private const val DOUBLE_TAP_SEEK_MS = 10_000L

@Composable
private fun SettingsScreen(
    initialToken: String,
    initialCacheSegments: Boolean,
    onSave: (token: String, cacheSegments: Boolean) -> Unit,
    onBack: () -> Unit,
) {
    var token by remember { mutableStateOf(initialToken) }
    var cacheSegments by remember { mutableStateOf(initialCacheSegments) }

    Scaffold(modifier = Modifier.fillMaxSize()) { innerPadding ->
        Column(
            modifier = Modifier
                .padding(innerPadding)
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text("设置", style = MaterialTheme.typography.titleLarge)

            OutlinedTextField(
                value = token,
                onValueChange = { token = it },
                label = { Text("百度网盘 access_token") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("缓存分片文件（占用手机空间）")
                Switch(checked = cacheSegments, onCheckedChange = { cacheSegments = it })
            }

            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Button(onClick = { onSave(token.trim(), cacheSegments) }) { Text("保存") }
                TextButton(onClick = onBack) { Text("返回") }
            }

            Text(
                "提示：修改缓存开关需重启播放服务生效；access_token 修改后立即生效。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

/** 用 mediaId=用户路径 触发播放；实际 URL 由 PlaybackService 的会话回调解析 */
private fun playPath(controller: Player, path: String) {
    val item = MediaItem.Builder().setMediaId(path.trim()).build()
    controller.setMediaItem(item)
    controller.prepare()
    controller.play()
}
