/** 视口段落定位工具（I-9 修复）：文本书当前视口顶部段落。 */

/**
 * 返回滚动容器中「当前视口顶部」的 data-para 序号（视口顶部 +24px 容差）。
 * 坐标系说明：`.para` 的 offsetTop 相对 `.reader`（position:relative），
 * 与滚动容器的坐标相差 el.offsetTop，必须统一参照系（与 scrollToPara 一致）。
 *
 * hint：上一次命中段的数组下标（滚动时从附近双向扩散，避免每次从头 O(P) 扫描）。
 * 段落满足「bottom > 视口顶」的谓词关于下标单调（文档流 offsetTop 递增），
 * 命中集是后缀区间——向左扫到边界、未中再向右找第一个命中即全局首段。
 */
export function viewportTopPara(
  paras: HTMLElement[],
  el: HTMLElement,
  tolerance = 24,
  hint: number | null = null,
): number | null {
  if (!paras.length) return null
  const threshold = el.scrollTop + tolerance
  const satisfies = (p: HTMLElement) => p.offsetTop - el.offsetTop + p.offsetHeight > threshold
  const start = hint == null ? 0 : Math.max(0, Math.min(hint, paras.length - 1))
  if (hint != null) {
    // 向左找「最后一个命中」即全局首个命中段（命中集为后缀区间，递减扫到不命中即停）
    let leftHit = -1
    for (let i = start; i >= 0; i--) {
      if (!satisfies(paras[i])) break
      leftHit = i
    }
    if (leftHit >= 0) return Number(paras[leftHit].dataset.para)
    // 向左无命中 → 向右找第一个命中
    for (let i = start + 1; i < paras.length; i++) {
      if (satisfies(paras[i])) return Number(paras[i].dataset.para)
    }
    return null
  }
  for (let i = 0; i < paras.length; i++) {
    if (satisfies(paras[i])) return Number(paras[i].dataset.para)
  }
  return null
}
