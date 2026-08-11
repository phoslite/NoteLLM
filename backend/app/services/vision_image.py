"""视觉提取压缩页图（pages_vlm/）：裁边 + 缩放 + 空白预判 + OCR 预留扩展（v1.85 方案并入主程序，v1.86）。

- 阅读原图 pages/ 高分辨率不动；视觉提取输入用压缩图 pages_vlm/（分离，降 token/请求体/超时率）；
- 裁边默认 conservative（只裁 >=20px 完全空白边带）；aggressive（内容边界 + 保护带外扩 + padding）；
  none=不裁边；裁后 <原 50% 整页回退；
- 双页扫描检测（中间空带 >1.5% 页宽 + 两侧对称实质内容）-> 只裁四边、禁止裁中间；
- 空白预判：无内容或裁后非白比例 <0.05% -> blank=True（调用方直接落盘空白标记，不调多模态 API）；
- meta.json 记录参数签名，与配置不一致时整目录重建（批量=整目录重建；懒生成=渐进重建）；
- 原图宽 <= 阈值且无裁边收益时复用原图（不生成副本）；
- OCR 预留扩展：vision_ocr_engine 配置本地 OCR 引擎（tesseract 已实现；paddle/rapidocr 为预留占位），
  压缩图生成后同步产出 pages_vlm/page_XXX.txt，视觉提取优先使用 OCR 文本（省多模态调用）。
"""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pymupdf

from app.core.config import settings
from app.services.media_service import page_image_path

VLM_DIR = "pages_vlm"
META_FILE = "meta.json"

# ---- v1.85 定稿默认参数（与 demo/trim_demo.py 一致） ----
GRAY_THRESHOLD = 200        # 亮度 <200 视为墨迹
DENSITY_THRESHOLD = 0.001   # 行/列墨迹比例 >0.1% 才算内容
SMOOTH = 7                  # 投影滑动窗口平滑
MIN_BAND_PX = 20            # 安全模式最小边带（原图像素）
PROTECT_ZONE_PX = 16        # 激进模式边界保护带（原图像素）
PADDING_PX = 16             # 激进模式外扩 padding
SPREAD_GAP_RATIO = 0.015    # 双页检测：中间空带 >1.5% 页宽（装订缝 1~5%）
SPREAD_SIDE_MIN = 0.25      # 双页两侧内容宽度下限（各约半页）
SPREAD_SIDE_MAX = 0.70
SPREAD_SYMM_MAX = 1.67      # 两侧宽度比上限（排版书分栏空隙不对称，被排除）
BLANK_RATIO = 0.0005        # 空白预判：非白比例 <0.05%
FALLBACK_RATIO = 0.50       # 裁后面积 <原 50% 回退
ANALYZE_WIDTH = 1000        # 分析分辨率宽度（600 下浅色细线易丢失，demo 实测提高至 1000）

# meta 校验/整目录重建临界区（批量预生成与懒生成并发时保护）
_meta_lock = threading.Lock()


def vlm_page_path(book, page_index: int) -> Path:
    """压缩图路径：data/books/<书目录>/pages_vlm/page_XXX.jpg。"""
    return Path(book.file_path).parent / VLM_DIR / f"page_{page_index:03d}.jpg"


def _meta_path(book) -> Path:
    return Path(book.file_path).parent / VLM_DIR / META_FILE


def _signature() -> dict:
    # I-4 修复：OCR 引擎/语言/可执行文件纳入签名——切换 OCR 配置后旧 page_*.txt 缓存
    # 必须失效重建，否则旧引擎/旧语言文本继续进 RAG（F7 在 OCR 维度复发）。
    return {
        "max_width": settings.vision_image_max_width,
        "quality": settings.vision_image_quality,
        "trim": settings.vision_image_trim,
        "ocr_engine": (settings.vision_ocr_engine or "").strip(),
        "ocr_lang": (settings.vision_ocr_lang or "").strip(),
        "ocr_bin": (settings.vision_ocr_bin or "").strip(),
    }


def _meta_valid(book) -> bool:
    """meta.json 参数签名与当前配置一致。"""
    path = _meta_path(book)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return data.get("params") == _signature()


def _write_meta(book) -> None:
    path = _meta_path(book)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"params": _signature(), "version": 1}
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _purge_vlm(book) -> None:
    """删除整目录压缩图与 OCR 文本缓存（参数变更重建；meta 由调用方重写）。"""
    root = Path(book.file_path).parent / VLM_DIR
    if root.is_dir():
        for f in root.glob("page_*.jpg"):
            f.unlink(missing_ok=True)
        for f in root.glob("page_*.txt"):
            f.unlink(missing_ok=True)


def _load_gray(path: Path):
    """渲染到分析宽度灰度图；返回 (gray, w, h, scale, orig_w, orig_h)。

    注：pymupdf.Pixmap.shrink 实测行为异常（6024px 缩 10 倍得 6px），改用图片文档
    get_pixmap(matrix=zoom, colorspace=csGRAY) 渲染；page.rect.width 是 pt（受 DPI 影响），
    原图像素尺寸用 Pixmap.width/height（否则 scale 失真）。
    """
    pix_orig = pymupdf.Pixmap(str(path))
    orig_w, orig_h = pix_orig.width, pix_orig.height
    doc = pymupdf.open(str(path))
    try:
        page = doc[0]
        zoom = ANALYZE_WIDTH / page.rect.width if page.rect.width > ANALYZE_WIDTH else 1.0
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY)
    finally:
        doc.close()  # 审查 I-2：异常路径不再泄漏文档句柄
    w, h = pix.width, pix.height
    gray = bytearray(pix.samples)
    if pix.stride != w:
        out = bytearray(w * h)
        for y in range(h):
            out[y * w:(y + 1) * w] = gray[y * pix.stride:y * pix.stride + w]
        gray = out
    return gray, w, h, orig_w / w, orig_w, orig_h


def _ink_stats(gray, w, h):
    row_ink = [0] * h
    col_ink = [0] * w
    for y in range(h):
        base = y * w
        cnt = 0
        for x in range(w):
            if gray[base + x] < GRAY_THRESHOLD:
                cnt += 1
                col_ink[x] += 1
        row_ink[y] = cnt
    return row_ink, col_ink


def _smooth(vals, k=SMOOTH):
    n = len(vals)
    out = [0.0] * n
    half = k // 2
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        out[i] = sum(vals[lo:hi]) / (hi - lo)
    return out


def _content_span(vals_smooth, axis_len):
    idx = [i for i, v in enumerate(vals_smooth) if v / axis_len > DENSITY_THRESHOLD]
    if not idx:
        return None
    return (idx[0], idx[-1] + 1)


def _zone_ink(axis_ink, start, end):
    """边带 [start, end) 内墨迹像素总数（安全模式「完全无墨迹」判定）。"""
    return sum(axis_ink[start:end])


def _detect_spread(gray, w, h, col_ink, row_ink):
    """双页扫描检测：中间空带 >1.5% 页宽 + 两侧是**对称实质内容页**。

    排版书分栏/列表空隙两侧不对称（demo 实测页 4=32%/62%、页 190=24%/43%），被对称性判据排除。
    返回 (is_spread, gap_start, gap_end)。
    """
    content = [col_ink[x] / h > DENSITY_THRESHOLD for x in range(w)]
    best = (0, -1, -1)
    start = None
    for x in range(w + 1):
        is_empty = x < w and not content[x]
        if is_empty and start is None:
            start = x
        elif not is_empty and start is not None:
            length = x - start
            if length > best[0] and start > 0 and x < w and any(content[0:start]) and any(content[x:w]):
                best = (length, start, x)
            start = None
    gap_len, gap_start, gap_end = best
    if gap_len <= SPREAD_GAP_RATIO * w or gap_start <= 0:
        return False, None, None
    cols = [x for x in range(w) if content[x]]
    l0, l1 = cols[0], gap_start
    r0, r1 = gap_end, cols[-1] + 1
    left_w = l1 - l0
    right_w = r1 - r0
    if not (SPREAD_SIDE_MIN * w <= left_w <= SPREAD_SIDE_MAX * w
            and SPREAD_SIDE_MIN * w <= right_w <= SPREAD_SIDE_MAX * w):
        return False, None, None
    if max(left_w, right_w) / max(1, min(left_w, right_w)) > SPREAD_SYMM_MAX:
        return False, None, None
    left_ink = sum(col_ink[l0:l1])
    right_ink = sum(col_ink[r0:r1])
    total_ink = left_ink + right_ink + sum(col_ink[gap_start:gap_end])
    if total_ink <= 0 or left_ink < 0.15 * total_ink or right_ink < 0.15 * total_ink:
        return False, None, None
    row_span = _content_span(_smooth(row_ink), w)
    if row_span is None or (row_span[1] - row_span[0]) < 0.4 * h:
        return False, None, None
    return True, gap_start, gap_end


def _trim_bbox(row_ink, col_ink, w, h, scale, mode: str, is_spread: bool = False):
    """返回裁边 bbox（分析坐标，原图坐标由调用方乘以 scale 换算）；无内容返回 None。

    mode: conservative（只裁 >=MIN_BAND_PX 且完全无墨迹的边带）| aggressive
    （内容边界 + 保护带墨迹外扩 + padding）| none（不裁）。
    is_spread: 双页扫描（_detect_spread 判定）——中间空带永不裁，保留左右两页完整区间。
    scale = 原图宽 / 分析宽，MIN_BAND_PX 等阈值以原图像素计。
    """
    if mode == "none":
        return (0, 0, w, h)
    row_s = _smooth(row_ink)
    col_s = _smooth(col_ink)
    span_r = _content_span(row_s, w)
    span_c = _content_span(col_s, h)
    if span_r is None or span_c is None:
        return None  # 整页无内容（空白判定交给调用方）
    top0, bottom0 = span_r
    left0, right0 = span_c
    if mode == "aggressive":
        prot = max(1, int(PROTECT_ZONE_PX / scale))
        pad = max(1, int(PADDING_PX / scale))
        top, bottom, left, right = top0, bottom0, left0, right0
        # 上边保护带 [top0-prot, top0+prot] 内墨迹的最小行
        ztop = max(0, top0 - prot)
        zbottom = min(h, top0 + prot)
        for y in range(ztop, zbottom):
            if row_ink[y] > 0:
                top = max(0, y - pad)
                break
        # 下边保护带内墨迹的最大行
        ztop2 = max(0, bottom0 - prot)
        zbottom2 = min(h, bottom0 + prot)
        for y in range(zbottom2 - 1, ztop2 - 1, -1):
            if row_ink[y] > 0:
                bottom = min(h, y + pad + 1)
                break
        # 左边保护带内墨迹的最小列
        zl = max(0, left0 - prot)
        zr = min(w, left0 + prot)
        for x in range(zl, zr):
            if col_ink[x] > 0:
                left = max(0, x - pad)
                break
        # 右边保护带内墨迹的最大列
        zl2 = max(0, right0 - prot)
        zr2 = min(w, right0 + prot)
        for x in range(zr2 - 1, zl2 - 1, -1):
            if col_ink[x] > 0:
                right = min(w, x + pad + 1)
                break
    else:
        # conservative：只裁「完全无墨迹」且原图像素宽度 >= MIN_BAND_PX 的边带
        top, bottom, left, right = 0, h, 0, w
        if _zone_ink(col_ink, 0, left0) == 0 and left0 * scale >= MIN_BAND_PX:
            left = left0
        if _zone_ink(col_ink, right0, w) == 0 and (w - right0) * scale >= MIN_BAND_PX:
            right = right0
        if _zone_ink(row_ink, 0, top0) == 0 and top0 * scale >= MIN_BAND_PX:
            top = top0
        if _zone_ink(row_ink, bottom0, h) == 0 and (h - bottom0) * scale >= MIN_BAND_PX:
            bottom = bottom0
    if is_spread:
        # 双页扫描：左右内容页区间已由 span 保底，防御性显式恢复，中间空带永不裁
        left, right = left0, right0
    return (left, top, right, bottom)


def _blank_ratio(gray, w, h, left, top, right, bottom) -> float:
    """裁剪区域内非白像素比例（<BLANK_RATIO 判空白）。"""
    total = (bottom - top) * (right - left)
    if total <= 0:
        return 1.0
    ink = 0
    for y in range(top, bottom):
        base = y * w
        for x in range(left, right):
            if gray[base + x] < GRAY_THRESHOLD:
                ink += 1
    return ink / total


def _render_cropped(src_path: Path, bbox_orig, out_path: Path, max_width: int, quality: int) -> Path:
    """从原图重渲染：裁边 clip + 缩放 + JPEG 保存（不放大分析图，保持原图清晰度）。

    原图像素坐标 → 页面 pt 坐标按各自轴比例换算（JPEG 自带 DPI 会让 page.rect 与像素不成 1:1）。
    """
    doc = pymupdf.open(str(src_path))
    try:
        page = doc[0]
        pix0 = pymupdf.Pixmap(str(src_path))
        sx = page.rect.width / pix0.width
        sy = page.rect.height / pix0.height
        clip = pymupdf.Rect(bbox_orig[0] * sx, bbox_orig[1] * sy,
                            bbox_orig[2] * sx, bbox_orig[3] * sy)
        zoom = max_width / clip.width if clip.width > max_width else 1.0
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip, alpha=False)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pix.save(str(out_path), jpg_quality=quality)
    finally:
        doc.close()
    return out_path


def prep_page_image(book, page_index: int) -> dict:
    """准备单页压缩图：读原图 → 分析裁边 → 空白预判 → 从原图重渲染到 pages_vlm/。

    返回 {"path", "source", "blank", "trimmed"}：
    - source="cached"：vlm 图已存在且参数未变（直接复用）；
    - source="original"：无裁边收益且原图 <= max_width，复用原图（不生成副本）；
    - source="new"：裁边重渲染生成 vlm 图；
    - source="blank"：空白页（不生成 vlm 图，调用方直接落盘空白标记）。
    纯函数（无 Session），可并发调用；meta 校验/重建临界区加锁保护。
    """
    src = page_image_path(book, page_index)
    if not src.exists():
        raise FileNotFoundError(f"页图缺失: {src}")
    vlm = vlm_page_path(book, page_index)
    with _meta_lock:
        if _meta_valid(book) and vlm.exists():
            return {"path": vlm, "source": "cached", "blank": False, "trimmed": False}
        if not _meta_valid(book) and any(vlm.parent.glob("page_*.jpg")):
            _purge_vlm(book)
    # B-I1：CPU 密集的灰阶/裁边/空白预判在锁外执行（原实现整段持全局锁，
    # 4 线程并行渲染被串行化且每页两次 glob 使整批退化为 O(N²) 目录遍历）
    gray, w, h, scale, orig_w, orig_h = _load_gray(src)
    row_ink, col_ink = _ink_stats(gray, w, h)
    is_spread, _, _ = _detect_spread(gray, w, h, col_ink, row_ink)  # 双页扫描判定（v1.120 接线）
    bbox = _trim_bbox(row_ink, col_ink, w, h, scale, settings.vision_image_trim, is_spread=is_spread)
    if bbox is None:
        return {"path": src, "source": "blank", "blank": True, "trimmed": False}
    left, top, right, bottom = bbox
    if _blank_ratio(gray, w, h, left, top, right, bottom) < BLANK_RATIO:
        return {"path": src, "source": "blank", "blank": True, "trimmed": False}
    bbox_orig = (round(left * scale), round(top * scale),
                 round(right * scale), round(bottom * scale))
    # 裁后 <原 50% 整页回退（内容极稀疏页防误裁，与 demo 参数一致）
    if 1.0 - ((right - left) * (bottom - top)) / (w * h) > (1.0 - FALLBACK_RATIO):
        bbox_orig = (0, 0, orig_w, orig_h)
    trimmed = bbox_orig != (0, 0, orig_w, orig_h)
    if not trimmed and orig_w <= settings.vision_image_max_width:
        return {"path": src, "source": "original", "blank": False, "trimmed": False}
    with _meta_lock:
        # F7 修正：仅当存在旧压缩图时才 purge（连带清 OCR txt）；无旧图时保留已写入的 OCR 缓存
        if not _meta_valid(book) and any(vlm.parent.glob("page_*.jpg")):
            _purge_vlm(book)  # 并发窗口内参数变更兜底（批量入口已串行 purge）
        # meta 先写再渲染：渲染在锁外（幂等，同参同源输出相同文件），
        # 锁内保持短临界区；渲染失败时 meta 已就绪但 vlm 缺失 → 下次调用自然重渲染
        _write_meta(book)
    _render_cropped(src, bbox_orig, vlm,
                    settings.vision_image_max_width, settings.vision_image_quality)
    return {"path": vlm, "source": "new", "blank": False, "trimmed": trimmed}


def prepare_book_vlm_images(book, workers: int | None = None, progress: object | None = None) -> dict:
    """批量预生成全书压缩页图（归档/导入后台；参数变更整目录重建）。

    workers 默认 page_render_concurrency；OCR 已配置时同步产出页 OCR 文本缓存（失败不中断）。
    返回 {"total", "ok", "skipped", "blank", "purged", "ocr", "errors"}。
    """
    pages_dir = Path(book.file_path).parent / "pages"
    page_nos = []
    for f in sorted(pages_dir.glob("page_*.jpg")):
        try:
            page_nos.append(int(f.stem.split("_")[1]))
        except (IndexError, ValueError):
            continue
    total = len(page_nos)
    stats = {"total": total, "ok": 0, "skipped": 0, "blank": 0, "purged": 0, "ocr": 0, "errors": []}
    if total == 0:
        return stats
    with _meta_lock:
        if not _meta_valid(book):
            if any((Path(book.file_path).parent / VLM_DIR).glob("page_*.jpg")):
                _purge_vlm(book)
                stats["purged"] = 1
            _write_meta(book)
    if workers is None:
        workers = settings.page_render_concurrency
    lock = threading.Lock()
    done = 0

    def _one(page_index: int) -> None:
        nonlocal done
        try:
            res = prep_page_image(book, page_index)
            with lock:
                if res["blank"]:
                    stats["blank"] += 1
                elif res["source"] == "cached":
                    stats["skipped"] += 1
                else:
                    stats["ok"] += 1
                if _ocr_enabled() and not res["blank"] and _ocr_cache_for(book, page_index, res["path"]):
                    stats["ocr"] += 1
                done += 1
                if progress is not None:
                    progress(done, total)
        except Exception as exc:  # noqa: BLE001 单页失败不中断整体
            with lock:
                stats["errors"].append(f"第 {page_index} 页: {exc}")
                done += 1
                if progress is not None:
                    progress(done, total)

    if workers <= 1 or total <= 1:
        for idx in page_nos:
            _one(idx)
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="vlm-prep") as pool:
            list(pool.map(_one, page_nos))
    return stats


# ---- OCR 预留扩展（v1.86）：本地 OCR 引擎接入点 ----

def ocr_configured() -> bool:
    """是否配置了 OCR 引擎（vision_ocr_engine 非空）。"""
    return bool((settings.vision_ocr_engine or "").strip())


def _ocr_enabled() -> bool:
    return ocr_configured()


def ocr_text_path(book, page_index: int) -> Path:
    """OCR 文本缓存：pages_vlm/page_XXX.txt（与压缩图同目录，参数变更随整目录重建）。"""
    return vlm_page_path(book, page_index).with_suffix(".txt")


def read_ocr_cache(book, page_index: int) -> str | None:
    """读取 OCR 文本缓存；不存在或为空返回 None。"""
    path = ocr_text_path(book, page_index)
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


def write_ocr_cache(book, page_index: int, text: str) -> Path:
    path = ocr_text_path(book, page_index)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def ocr_page_text(img_path: Path) -> str | None:
    """调用配置的本地 OCR 引擎提取图片文本；未配置/未实现/失败返回 None（调用方回退视觉模型）。

    预留扩展点：vision_ocr_engine 新增引擎时在此添加分支（如 paddle → _ocr_paddleocr）。
    各引擎实现约定：输入单页图片路径，返回完整文本（含换行）或 None。
    """
    engine = (settings.vision_ocr_engine or "").strip().lower()
    if engine == "tesseract":
        return _ocr_tesseract(img_path)
    # 预留占位：paddleocr / rapidocr / easyocr 等引擎接入点（返回 None 即回退多模态）
    return None


def _ocr_tesseract(img_path: Path) -> str | None:
    """Tesseract OCR（subprocess 调用；vision_ocr_bin 可指定可执行文件，默认走 PATH）。"""
    import subprocess

    binary = (settings.vision_ocr_bin or "tesseract").strip()
    lang = (settings.vision_ocr_lang or "eng").strip()
    try:
        proc = subprocess.run(
            [binary, str(img_path), "stdout", "-l", lang],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    text = proc.stdout.strip()
    return text or None


def _ocr_cache_for(book, page_index: int, img_path: Path) -> bool:
    """按需 OCR 并落盘缓存；返回是否成功产出非空文本（已有缓存视为成功）。"""
    if read_ocr_cache(book, page_index):
        return True
    text = ocr_page_text(img_path)
    if not text:
        return False
    write_ocr_cache(book, page_index, text)
    return True
