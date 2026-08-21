"""M3U8 重写工具

只保留代理真正用到的能力：移除 `#EXT-X-KEY`（加密密钥）标签。
解析/生成等死代码已删除，避免误导后续维护者。
"""


def rewrite_m3u8(content: bytes, keep_key: bool = False) -> bytes:
    """重写 m3u8 内容，默认移除 #EXT-X-KEY（加密密钥）标签。

    URI 不做任何前缀改写：分片 / 变体 / #EXT-X-MAP 等相对地址原样保留，
    HLS 播放器会相对 m3u8 自身的 URL 解析，因此无论应用挂在根路径还是
    nginx 子路径（如 /movies）下，分片都能正确命中代理。
    绝对地址（http(s):// 或 //）同样保持不变。解析失败时原样返回。
    """
    try:
        text = content.decode('utf-8')
    except (UnicodeDecodeError, AttributeError):
        return content

    lines = []
    for line in text.split('\n'):
        stripped = line.strip()
        if stripped and not keep_key and stripped.startswith('#EXT-X-KEY:'):
            continue  # 默认去掉加密密钥标签
        lines.append(line)

    return '\n'.join(lines).encode('utf-8')
