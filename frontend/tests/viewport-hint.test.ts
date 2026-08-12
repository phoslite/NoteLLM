import { describe, expect, it } from 'vitest'
import { viewportTopPara } from '../src/utils/viewport'

/** P1-1：hint 双向扩散查找——结果与无 hint 全量扫描一致。
 *  几何：段 i offsetTop = el.offsetTop + 10 + 20i，bottom 换算 = 30 + 20i；
 *  满足「bottom > scrollTop + tolerance」的段 i 即首段。 */
function makeParas(count: number, el: { offsetTop: number; scrollTop: number }) {
  const paras: HTMLElement[] = []
  let offsetTop = el.offsetTop + 10
  for (let i = 0; i < count; i++) {
    paras.push({
      offsetTop,
      offsetHeight: 20,
      dataset: { para: String(i) },
    } as unknown as HTMLElement)
    offsetTop += 20
  }
  return paras
}

describe('P1-1 · viewportTopPara hint 双向扩散', () => {
  it('hint 在命中段下方：向左找边界；在命中段上方：向右找首个命中', () => {
    const el = { offsetTop: 100, scrollTop: 170 } as HTMLElement
    const paras = makeParas(10, el)
    // 30 + 20i > 170 + 24 = 194 → i ≥ 9
    expect(viewportTopPara(paras, el, 24, 9)).toBe(9) // hint 恰为命中段
    expect(viewportTopPara(paras, el, 24, 0)).toBe(9) // 从段 0 向左无命中 → 向右找到 9
    expect(viewportTopPara(paras, el)).toBe(9) // 无 hint 全量扫描一致
  })

  it('hint 左侧存在更小命中段时返回全局首个命中（向左找边界）', () => {
    const el = { offsetTop: 100, scrollTop: 100 } as HTMLElement
    const paras = makeParas(10, el)
    // 30 + 20i > 100 + 24 = 124 → i ≥ 5；hint=7 满足且 5/6 也满足 → 应返回 5
    expect(viewportTopPara(paras, el, 24, 7)).toBe(5)
    expect(viewportTopPara(paras, el, 24, 5)).toBe(5)
    expect(viewportTopPara(paras, el, 24, 8)).toBe(5)
    expect(viewportTopPara(paras, el)).toBe(5)
  })

  it('hint 在命中段下方且向左全部命中时返回边界（首段即命中）', () => {
    const el = { offsetTop: 100, scrollTop: 0 } as HTMLElement
    const paras = makeParas(10, el)
    // 30 + 20i > 24 对 i ≥ 0 恒成立 → 首段 0
    expect(viewportTopPara(paras, el, 24, 6)).toBe(0)
  })

  it('全部段落在视口上方时返回 null（hint 与无 hint 一致）', () => {
    const el = { offsetTop: 100, scrollTop: 1000 } as HTMLElement
    const paras = makeParas(5, el)
    expect(viewportTopPara(paras, el, 24, 2)).toBeNull()
    expect(viewportTopPara(paras, el)).toBeNull()
  })

  it('hint 越界时钳制到有效范围', () => {
    const el = { offsetTop: 100, scrollTop: 170 } as HTMLElement
    const paras = makeParas(10, el)
    expect(viewportTopPara(paras, el, 24, 999)).toBe(9)
    expect(viewportTopPara(paras, el, 24, -5)).toBe(9)
  })

  it('空数组返回 null', () => {
    const el = { offsetTop: 0, scrollTop: 0 } as HTMLElement
    expect(viewportTopPara([], el, 24, 0)).toBeNull()
  })
})