package xyz.asitanokibou.player.service

import androidx.media3.session.MediaSession
import androidx.media3.session.MediaSessionService

/**
 * 播放服务（P0 占位）。
 *
 * 后续阶段职责：
 *  - onCreate 时启动本地 Ktor 代理（127.0.0.1，自动端口），持有其生命周期
 *  - 创建并持有 ExoPlayer 与 MediaSession
 *  - 以 mediaPlayback 前台服务运行，通知栏提供播放控制、息屏保活
 */
class PlaybackService : MediaSessionService() {

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaSession? {
        // TODO(P4): 返回持有 ExoPlayer 的 MediaSession
        return null
    }
}
