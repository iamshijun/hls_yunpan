# hls_pan_player (Android)

将网盘 HLS 代理服务改造为 Android 原生 App：本地 Ktor 代理 + Media3 ExoPlayer 播放。

- 包名：`xyz.asitanokibou.player`
- minSdk：30（Android 11），targetSdk / compileSdk：34
- 工具链：AGP 8.1.4 / Gradle 8.2 / Kotlin 1.9.22（适配 Android Studio Giraffe 2022.3.1）
- UI：Jetpack Compose（Compose 编译器扩展 1.5.10）
- 播放：Media3 ExoPlayer（HLS），统一由 `PlaybackService`（MediaSessionService）托管
- 本地代理与百度下载：Ktor Server / Client（CIO）
- fsid 缓存：仅内存（MVP）

## 当前进度：P0（工程骨架）

已就绪：Gradle 配置（版本目录 `gradle/libs.versions.toml`）、`AndroidManifest`（权限 + 前台服务 + 明文回环放行）、空的 Compose `MainActivity`、`PlaybackService` 占位。

## 在 Android Studio 打开

1. Android Studio 选择 **Open**，打开本 `android/` 目录（不是仓库根）。
2. 首次会自动生成 `local.properties`（含本机 SDK 路径）和 Gradle Wrapper。
   - 若命令行构建，需先执行 `gradle wrapper --gradle-version 8.2` 生成 wrapper（本骨架未附带 `gradlew` 二进制）。
3. Sync 后运行 `app`，应能启动一个显示占位文案的空壳界面。

> 注意：本仓库这边无 Android SDK/Gradle 环境，代码由对话编写，编译与真机调试请在 Android Studio 进行，报错再一起修。

## 后续阶段（规划）

- P1 `baidu/BaiduYunClient`：文件列表 / 下载 / 流式下载（对齐 Python `baiduyun_service.py`）
- P2 `cache/FsidStore`(内存) + `cache/FileCache`
- P3 `proxy/HlsProxyHandler` + `proxy/M3u8Rewriter`
- P4 `proxy/ProxyServer`(Ktor) + `service/PlaybackService`(ExoPlayer + 前台)
- P5 Compose UI（路径输入 / 设置页）+ PlayerView + MediaController
- P6 权限运行时申请 / 通知栏控制 / 息屏保活
- P7 真机联调与加固
