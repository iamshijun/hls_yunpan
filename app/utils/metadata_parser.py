"""metadata.txt 解析工具

解析形如 `key:value` 的简单文本格式：
- 以 `#` 开头的行视为注释，跳过
- value 含 `,` → 拆成 list（strip 空串）
- `label` 与 `tag` 合并到 `tags`，按首次出现顺序去重
- 其他字段原样保留（value 为字符串或 list）
"""
from typing import Any, Dict


def _coerce_value(raw: str) -> Any:
    """含逗号则拆成 list（strip 空串），否则返回 strip 后的字符串。"""
    value = raw.strip()
    if "," in value:
        parts = [p.strip() for p in value.split(",")]
        parts = [p for p in parts if p]
        return parts if parts else ""
    return value


def _dedup_preserve_order(items):
    """去重保序：保留首次出现位置。"""
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def parse_metadata(text: str) -> Dict[str, Any]:
    """解析 metadata.txt 的 key:value 行。

    Returns:
        dict: 字段集合。`label` 与 `tag` 合并到 `tags`，去重保序。
    """
    result: Dict[str, Any] = {}
    tags: list = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # 允许使用 `=` 或 `:` 分隔（兼容两种写法）
        # 优先尝试 `=`，避免值含 `:`（如 URL `http://...`）时被误切
        for sep in ("=", ":"):
            if sep in line:
                key, _, value = line.partition(sep)
                key = key.strip().lower()
                if not key:
                    break
                coerced = _coerce_value(value)
                if key in ("label", "tag"):
                    # 允许 value 是 list 或单值，统一聚合
                    if isinstance(coerced, list):
                        tags.extend(coerced)
                    elif coerced != "":
                        tags.append(coerced)
                else:
                    result[key] = coerced
                break

    if tags:
        result["tags"] = _dedup_preserve_order(tags)

    return result
