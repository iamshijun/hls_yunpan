package xyz.asitanokibou.player.baidu.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * 百度网盘 API 响应 DTO。
 * 对齐 Python `baiduyun_service.py` 使用到的字段；未知字段忽略。
 */

@Serializable
data class FileListResponse(
    val errno: Int = -1,
    val errmsg: String? = null,
    val list: List<BaiduFile> = emptyList(),
)

@Serializable
data class BaiduFile(
    /** 完整网盘路径，如 /apps/movies/video1/playlist.m3u8 */
    val path: String = "",
    /** 文件系统 ID（64 位），对应 Python 中的 fs_id */
    @SerialName("fs_id") val fsId: Long = 0,
    /** 1 表示目录 */
    val isdir: Int = 0,
    @SerialName("server_filename") val serverFilename: String = "",
    val size: Long = 0,
)

@Serializable
data class FileMetasResponse(
    val errno: Int = -1,
    val errmsg: String? = null,
    val list: List<FileMeta> = emptyList(),
)

@Serializable
data class FileMeta(
    @SerialName("fs_id") val fsId: Long = 0,
    /** 下载直链（需带 access_token + UA=pan.baidu.com 访问） */
    val dlink: String? = null,
    val path: String? = null,
)
