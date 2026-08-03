"""跨书关联边小工具：书对键规范化等。"""

def pair_key(x: int, y: int) -> tuple[int, int]:
    """规范化无序书对：较小 id 在前，(a, b) 与 (b, a) 使用同一键。"""
    return (x, y) if x < y else (y, x)
