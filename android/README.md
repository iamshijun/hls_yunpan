# hls_pan_player (Android)

将网盘 HLS 代理服务改造为 Android 原生 App：本地 Ktor 代理 + Media3 ExoPlayer 播放。

- 包名：`xyz.asitanokibou.player`
- minSdk：30（Android 11），targetSdk / compileSdk：34
- 工具链：AGP 8.1.4 / Gradle 8.2 / Kotlin 1.9.22（适配 Android Studio Giraffe 2022.3.1）
- UI：Jetpack Compose（Compose 编译器扩展 1.5.10）
- 播放：Media3 ExoPlayer（HLS），统一由 `PlaybackService`（MediaSessionService）托管
- 本地代理与百度下载：Ktor Server / Client（CIO）
- fsid 缓存：仅内存（MVP）

## 当前进度

P0–P7 已完成，端到端可跑：

- P0 工程骨架（Gradle / Compose / Manifest）
- P1 `baidu/BaiduYunClient`（list / dlink / 整包 / 流式）
- P2 `cache/FsidStore`(内存) + `cache/FileCache`
- P3 `proxy/HlsProxyHandler` + `proxy/M3u8Rewriter`
- P4 `proxy/ProxyServer`(Ktor) + `service/PlaybackService`(ExoPlayer + 前台)
- P5 Compose UI + MediaController + PlayerView
- P6 通知权限 / 音频焦点 / 网络唤醒 / 任务移除 / 错误展示
- P7 锁紧网络安全、自适应图标、错误透出

## 运行步骤

1. Android Studio 选择 **Open**，打开本 `android/` 目录（不是仓库根）。
2. 首次自动生成 `local.properties`（SDK 路径）和 Gradle Wrapper。
   - 若命令行构建，先 `gradle wrapper --gradle-version 8.2` 生成 wrapper。
3. **重要**：第一次 Sync 后若 IDE 报 `kotlinx.serialization compiler plugin is not applied`，做 `File → Invalidate Caches / Restart`（编译本身不受影响）。
4. 真机 / 模拟器运行 `app`。
5. 启动后：
   - 授予「通知」权限（Android 13+）；
   - 进入「设置」填写百度网盘 `access_token`（设置页保存即生效）；
   - 返回主页输入网盘目录名（如 `video1`，对应 `/apps/movies/video1/playlist.m3u8`），点播放。

## 已知限制（MVP 范围）

- **目录约定**：`/apps/movies/<输入路径>/playlist.m3u8`，与 Python 版一致。如需改路径前缀，调整 `PlaybackService` 里 `hlsRootPath` 与 `buildPlaylistUri`。
- **本地模式**：未实现（手机端单实例，走云端）。
- **Redis fsid 共享**：未实现（单实例，内存 fsid 已够用）。
- **缓存开关**：`cacheEnabled` / `cacheSegments` / `cacheTtlSec` 启动时快照；改动需重启播放服务（杀进程重开）。
- **access_token**：过期后仅在第一次网络请求时才会被百度端拒绝（错误会显示在 UI）。重新进入「设置」覆盖新 token 即可（立即生效）。

## 真机联调

- 看代理是否启动：`adb shell logcat -s ProxyServer:BaiduYunClient:HlsProxyHandler:PlaybackService`
- 看播放状态：错误码与 `errorCodeName` 会在主页显示。

