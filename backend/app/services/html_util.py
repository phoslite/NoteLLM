"""HTML 工具：文本提取与安全消毒（EPUB 方案 A，供解析/聊天/RAG/图谱/搜索复用）。

- html_to_text：HTML → 纯文本（块级元素换行），供 LLM 上下文、RAG 切块、关键词/聚类语料使用；
- scrub_html：服务端纵深防御消毒——移除脚本/嵌入类标签与事件属性、javascript: URL；
  排版保留（style 属性与 <style> 由前端 DOMPurify 做 CSS 白名单消毒，见 需求-决策 决策31/EPUB）；
- chapter_plain_text：按书籍格式取正文纯文本（epub → html_to_text，其余原样返回）。
"""
import posixpath
from html.parser import HTMLParser

_BLOCK_TAGS = {
    "p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "blockquote",
    "pre", "section", "article", "header", "footer", "figure", "figcaption",
    "table", "ul", "ol", "dl", "dt", "dd", "hr", "br",
}
# 服务端剔除的危险/嵌入标签（渲染层另有 DOMPurify 兜底）
_FORBIDDEN_TAGS = {
    "script", "iframe", "object", "embed", "form", "base", "link", "meta",
    "template", "noscript", "applet", "frame", "frameset",
}
_IMAGE_ATTRS = {"src", "href", "xlink:href", "poster"}
_ALLOWED_SCHEMES = ("http://", "https://", "data:", "mailto:", "tel:", "cid:", "#", ";")


class _TextExtractor(HTMLParser):
    """块级元素与 <br> 换行、跳过 script/style 内容的纯文本提取。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "br":
            self.parts.append("\n")
        elif tag in _BLOCK_TAGS and self.parts and not self.parts[-1].endswith("\n"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK_TAGS and self.parts and not self.parts[-1].endswith("\n"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        lines = []
        for line in "".join(self.parts).splitlines():
            line = line.strip()
            if line:
                lines.append(line)
        return "\n".join(lines)


def html_to_text(html: str) -> str:
    """HTML → 纯文本；解析异常返回空字符串（不影响正文流程）。"""
    if not html:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:
        return ""
    return parser.text()


class _ScrubParser(HTMLParser):
    """服务端消毒 + 图片引用重写（一次遍历完成）。

    - 剔除 _FORBIDDEN_TAGS 与 on* 事件属性；
    - href/src/xlink:href/poster 指向 zip 内图片（经 doc_dir 归一化后命中 image_map）时
      重写为 images/<name>（复用决策 31 媒体端点）；其余 URL 保留。
    """

    def __init__(self, image_map: dict[str, str] | None, doc_dir: str):
        super().__init__(convert_charrefs=True)
        self.image_map = image_map or {}
        self.doc_dir = doc_dir
        self.out: list[str] = []
        self._skip_depth = 0

    @staticmethod
    def _render_attr(name: str, value: str) -> str:
        """属性序列化：转义 & 与 "，防止 &quot; 实体注入绕过 on* 过滤（审查 P1）。

        HTMLParser(convert_charrefs=True) 会把属性值内的 &quot; 解码为 "，
        若直接拼回 f'{k}="{v}"'，src="x&quot; onerror=..." 会重渲染出真实
        onerror 事件属性；转义后输出等价于原文，服务端消毒承诺不失效。
        """
        return f'{name}="{value.replace("&", "&amp;").replace(chr(34), "&quot;")}"'

    def _maybe_rewrite(self, name: str, value: str) -> str:
        if name.lower() not in _IMAGE_ATTRS or not self.image_map:
            return value
        v = value.strip()
        if not v or v.startswith(_ALLOWED_SCHEMES):
            return value
        anchor = ""
        path_part = v
        if "#" in v:
            path_part, anchor = v.split("#", 1)
            anchor = "#" + anchor
        resolved = posixpath.normpath(posixpath.join(self.doc_dir, path_part))
        target = self.image_map.get(resolved)
        return f"images/{target}{anchor}" if target else value

    def _safe_attrs(self, attrs):
        out_attrs = []
        for name, value in attrs:
            lower = name.lower()
            if lower.startswith("on"):
                continue  # 事件属性：onclick 等
            if lower == "href" or lower == "src" or lower == "xlink:href" or lower == "poster":
                value = self._maybe_rewrite(lower, value or "")
                if value.lower().startswith("javascript:"):
                    continue
            out_attrs.append((name, value))
        return out_attrs

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in _FORBIDDEN_TAGS:
            self._skip_depth += 1
            return
        safe = self._safe_attrs(attrs)
        if safe:
            rendered = " ".join(self._render_attr(k, v) if v is not None else k for k, v in safe)
            self.out.append(f"<{tag} {rendered}>")
        else:
            self.out.append(f"<{tag}>")

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        if tag in _FORBIDDEN_TAGS:
            return
        safe = self._safe_attrs(attrs)
        if safe:
            rendered = " ".join(self._render_attr(k, v) if v is not None else k for k, v in safe)
            self.out.append(f"<{tag} {rendered}/>")
        else:
            self.out.append(f"<{tag}/>")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _FORBIDDEN_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if not self._skip_depth:
            self.out.append(data)

    def handle_comment(self, data):
        pass  # 丢弃注释

    def result(self) -> str:
        return "".join(self.out)


def scrub_html(html: str, image_map: dict[str, str] | None = None, doc_dir: str = "") -> str:
    """服务端消毒 HTML；可选重写 zip 内图片引用。解析异常原样返回（前端 DOMPurify 兜底）。"""
    if not html:
        return ""
    parser = _ScrubParser(image_map, doc_dir)
    try:
        parser.feed(html)
    except Exception:
        return html
    return parser.result()


def chapter_plain_text(book_format: str | None, content: str) -> str:
    """按书籍格式取正文纯文本：epub → html_to_text；其余原样（md/txt 正文即文本）。"""
    if book_format == "epub":
        return html_to_text(content)
    return content
