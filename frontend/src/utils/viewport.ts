/** 视口段落定位工具（I-9 修复）：文本书当前视口顶部段落。 */

/**
 * 返回滚动容器中「当前视口顶部」的 data-para 序号（视口顶部 +24px 容差）。
 * 坐标系说明：`.para` 的 offsetTop 相对 `.reader`（position:relative），
 * 与滚动容器的坐标相差 el.offsetTop，必须统一参照系（与 scrollToPara 一致）。
 */
export function viewportTopPara(paras: HTMLElement[], el: HTMLElement, tolerance = 24): number | null {
  for (const p of paras) {
    if (p.offsetTop - el.offsetTop + p.offsetHeight > el.scrollTop + tolerance) {
      return Number(p.dataset.para)
    }
  }
  return null
}
