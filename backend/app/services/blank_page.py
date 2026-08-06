"""空白页标记：视觉模型判定页面为空白时落盘的统一标记与判断（轻量纯函数，无仓储依赖）。"""
import re

BLANK_PAGE_MARK = "<!-- 空白页 -->"


def is_blank_page_text(text: str) -> bool:
    """判断提取文本是否为「空白页」标记/描述（归一化判定，供下游过滤）。

    判定规则：去掉标点/空白/HTML 注释符号后，短文本（≤20 字符）且含空白关键词
    才判定为空白页——正常正文页文本不可能这么短，避免长正文误判。
    """
    if not text:
        return False
    norm = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]", "", text.strip().lower())
    if not norm:
        return True
    if len(norm) > 20:
        return False
    return any(
        key in norm
        for key in (
            "空白页", "本页空白", "无内容", "没有内容", "无文字", "没有任何内容",
            "空白", "blank", "empty", "nocontent", "无内容页",
        )
    )
