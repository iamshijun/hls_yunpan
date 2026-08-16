"""M3U8解析工具"""
import re
from typing import List, Dict, Optional
from dataclasses import dataclass

@dataclass
class M3U8Segment:
    """分片信息"""
    uri: str
    duration: float
    byte_range: Optional[str] = None
    program_date_time: Optional[str] = None

@dataclass
class M3U8Playlist:
    """播放列表信息"""
    version: int = 3
    target_duration: float = 0
    media_sequence: int = 0
    segments: List[M3U8Segment] = None
    is_variant: bool = False
    variant_streams: List[Dict] = None

    def __post_init__(self):
        if self.segments is None:
            self.segments = []
        if self.variant_streams is None:
            self.variant_streams = []

class M3U8Parser:
    """M3U8解析器"""

    def __init__(self):
        self.segment_pattern = re.compile(r'#EXTINF:([\d.]+)(?:,(.*))?\n(.+)')
        self.byte_range_pattern = re.compile(r'#EXT-X-BYTERANGE:(\d+)@(\d+)')
        self.program_date_time_pattern = re.compile(r'#EXT-X-PROGRAM-DATE-TIME:(.+)')

    def parse(self, content: str) -> M3U8Playlist:
        """
        解析m3u8内容

        Args:
            content: m3u8文件内容

        Returns:
            M3U8Playlist对象
        """
        playlist = M3U8Playlist()
        lines = content.strip().split('\n')

        current_segment = None
        i = 0

        while i < len(lines):
            line = lines[i].strip()

            # 跳过空行
            if not line:
                i += 1
                continue

            # 解析版本
            if line.startswith('#EXT-X-VERSION:'):
                playlist.version = int(line.split(':')[1])
            # 解析目标时长
            elif line.startswith('#EXT-X-TARGETDURATION:'):
                playlist.target_duration = float(line.split(':')[1])
            # 解析媒体序列号
            elif line.startswith('#EXT-X-MEDIA-SEQUENCE:'):
                playlist.media_sequence = int(line.split(':')[1])
            # 解析分片信息
            elif line.startswith('#EXTINF:'):
                duration_info = line[len('#EXTINF:'):].split(',')
                duration = float(duration_info[0])
                if current_segment is None:
                    current_segment = M3U8Segment(uri="", duration=duration)
                else:
                    current_segment.duration = duration
            # 解析字节范围
            elif line.startswith('#EXT-X-BYTERANGE:'):
                match = self.byte_range_pattern.match(line)
                if match and current_segment:
                    current_segment.byte_range = f"{match.group(1)}@{match.group(2)}"
            # 解析程序时间
            elif line.startswith('#EXT-X-PROGRAM-DATE-TIME:'):
                match = self.program_date_time_pattern.match(line)
                if match and current_segment:
                    current_segment.program_date_time = match.group(1)
            # 分片URI
            elif not line.startswith('#'):
                if current_segment:
                    current_segment.uri = line
                    playlist.segments.append(current_segment)
                    current_segment = None
                # 检查是否是变体播放列表
                elif line.endswith('.m3u8'):
                    playlist.is_variant = True

            i += 1

        return playlist

    def generate(self, playlist: M3U8Playlist, base_url: str = "") -> str:
        """
        生成m3u8内容

        Args:
            playlist: M3U8Playlist对象
            base_url: 基础URL

        Returns:
            m3u8文件内容字符串
        """
        lines = ['#EXTM3U']
        lines.append(f'#EXT-X-VERSION:{playlist.version}')
        lines.append(f'#EXT-X-TARGETDURATION:{int(playlist.target_duration)}')
        lines.append(f'#EXT-X-MEDIA-SEQUENCE:{playlist.media_sequence}')

        for segment in playlist.segments:
            extinf = f'#EXTINF:{segment.duration}'
            if segment.program_date_time:
                extinf += f',{segment.program_date_time}'

            lines.append(extinf)

            if segment.byte_range:
                lines.append(f'#EXT-X-BYTERANGE:{segment.byte_range}')

            # 如果提供了base_url，则重写URI
            if base_url and not segment.uri.startswith('http'):
                uri = f"{base_url.rstrip('/')}/{segment.uri}"
            else:
                uri = segment.uri

            lines.append(uri)

        lines.append('#EXT-X-ENDLIST')

        return '\n'.join(lines)

    def rewrite(self, content: bytes, keep_key: bool = False) -> bytes:
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