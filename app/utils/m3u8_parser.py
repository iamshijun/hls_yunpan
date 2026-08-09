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

    _URI_ATTR_RE = re.compile(r'URI="([^"]*)"')
    _ABSOLUTE_RE = re.compile(r'^(https?://|//)')

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

    def rewrite(self, content: bytes, base_url: str = "", keep_key: bool = False) -> bytes:
        """重写播放列表中的相对 URI，使其指向代理路径。

        同时处理两类行：
        - 裸 URI 行（分片 / 变体播放列表）：相对路径拼上 base_url 的目录。
        - 标签属性中的 URI（#EXT-X-MAP / #EXT-X-MEDIA 等）。

        默认移除 #EXT-X-KEY（加密密钥）标签；设置 keep_key=True 时保留并重写其 URI。
        绝对地址（http(s):// 或 //）保持不变。解析失败时原样返回。
        """
        try:
            text = content.decode('utf-8')
        except (UnicodeDecodeError, AttributeError):
            return content

        base_dir = '/'.join(base_url.split('/')[:-1])

        lines = []
        for line in text.split('\n'):
            stripped = line.strip()
            if not stripped:
                lines.append(line)
            elif stripped.startswith('#'):
                if not keep_key and stripped.startswith('#EXT-X-KEY:'):
                    continue  # 默认去掉加密密钥标签
                lines.append(self._rewrite_attr_uris(line, base_dir))
            else:
                lines.append(self._join_base(base_dir, line))

        return '\n'.join(lines).encode('utf-8')

    @classmethod
    def _join_base(cls, base_dir: str, uri: str) -> str:
        """相对 URI 拼上 base_dir；绝对地址原样返回。"""
        if cls._ABSOLUTE_RE.match(uri):
            return uri
        return f"{base_dir}/{uri}".replace('//', '/')

    @classmethod
    def _rewrite_attr_uris(cls, line: str, base_dir: str) -> str:
        """重写标签属性中的 URI，例如 #EXT-X-KEY:URI=\"key.key\"。"""
        def _repl(match):
            return f'URI="{cls._join_base(base_dir, match.group(1))}"'
        return cls._URI_ATTR_RE.sub(_repl, line)