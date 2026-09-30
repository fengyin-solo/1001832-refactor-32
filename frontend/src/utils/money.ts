/**
 * 养护资金金额展示的唯一出处。
 *
 * 列表、详情、概览卡片都用这里的 formatMoney，金额口径本身由后端
 * fund_finance 统一计算，前端只负责把同源数字按同一格式呈现。
 */

/** 千分位金额，保留两位小数；null/undefined 显示占位符。 */
export function formatMoney(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return '—'
  }
  return value.toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

/** 超支结论统一文案。 */
export function overspendLabel(conclusion: string): string {
  return conclusion === '超支' ? '超支' : '正常'
}
