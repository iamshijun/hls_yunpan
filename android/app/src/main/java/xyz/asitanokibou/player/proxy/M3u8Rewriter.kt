package xyz.asitanokibou.player.proxy

import android.util.Log

/**
 * m3u8 URL 改写（对齐 Python `hls_proxy_service._rewrite_m3u8_urls`）。
 *
 * 将播放列表中的相对分片路径改写为基于请求路径目录的根相对路径，
 * 例如 basePath=/hls/video1/playlist.m3u8，分片行 `segment_0001`
 * 改写为 `/hls/video1/segment_0001`；以 http 开头的绝对地址保持不变；
 * `#` 开头或空行原样保留。
 */
object M3u8Rewriter {

    fun rewrite(content: ByteArray, basePath: String): ByteArray {
        return try {
            val text = String(content, Charsets.UTF_8)
            // base_dir = '/'.join(base_path.split('/')[:-1])
            val baseDir = basePath.split("/").dropLast(1).joinToString("/")

            val result = text.split("\n").joinToString("\n") { line ->
                if (line.isNotEmpty() && !line.startsWith("#")) {
                    if (!line.startsWith("http")) {
                        "$baseDir/$line".replace("//", "/")
                    } else {
                        line
                    }
                } else {
                    line
                }
            }
            result.toByteArray(Charsets.UTF_8)
        } catch (e: Exception) {
            Log.e("M3u8Rewriter", "重写m3u8 URL失败: $e")
            content
        }
    }
}
