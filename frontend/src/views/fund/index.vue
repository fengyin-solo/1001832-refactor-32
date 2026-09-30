<template>
  <section class="page" data-module="fund">
    <header class="page-head">
      <div>
        <h2>养护资金管理</h2>
        <p class="page-desc">维护资金记录，围绕资金编号、费用类别、项目名称、批复金额做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记资金记录</button>
        <button class="btn" type="button" @click="exportRows">导出养护资金清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong
          class="stat-value"
          :class="{ 'money-negative': item.type === 'money' && item.value < 0 }"
        >{{ item.type === 'money' ? moneyText(item.value) : item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>资金编号</span>
        <input v-model="keyword" placeholder="按资金编号检索" />
      </label>
      <label class="filter-item">
        <span>资金状态</span>
        <input v-model="status" placeholder="待审批/已批复/执行中/已超支" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <template v-if="moneyColumns.includes(column)">{{ moneyText(row[column]) }}</template>
            <template v-else-if="column === '超支结论'">
              <span :class="row[column] === '超支' ? 'tag-danger' : 'tag-ok'">{{ row[column] ?? '—' }}</span>
            </template>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">查看明细</button>
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无养护资金数据，可先登记资金记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条养护资金记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal-card">
        <header class="modal-head">
          <h3>资金明细 · {{ detail.资金编号 ?? '—' }}</h3>
          <button class="link" type="button" @click="detail = null">关闭</button>
        </header>
        <table class="data-table">
          <tbody>
            <tr v-for="item in detailRows" :key="item.label">
              <th>{{ item.label }}</th>
              <td :class="{ 'money-negative': item.money && Number(item.value) < 0 }">
                <template v-if="item.money">{{ moneyText(item.value) }}</template>
                <template v-else>{{ item.value ?? '—' }}</template>
              </td>
            </tr>
          </tbody>
        </table>
        <p class="modal-tip">
          金额由统一口径（{{ caliberLabel }}）计算；批复留档金额按批复当时口径冻结，不随后续调整改写。
        </p>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'
import { formatMoney } from '@/utils/money'

type Row = Record<string, string | number | null>
type Detail = {
  id?: number | null
  资金编号?: string | null
  费用类别?: string | null
  项目名称?: string | null
  批复金额?: number | null
  已用金额?: number | null
  剩余额度?: number | null
  超支结论?: string | null
  列支已结算?: number | null
  列支待结算?: number | null
  资金状态?: string | null
  审批人员?: string | null
  批复留档金额?: number | null
  批复口径版本?: string | null
  批复时间?: string | null
}

const ENDPOINT = '/api/fund'
const columns = ['资金编号', '费用类别', '项目名称', '批复金额', '已用金额', '剩余额度', '超支结论', '审批人员', '资金状态']
const moneyColumns = ['批复金额', '已用金额', '剩余额度']
const actions = ['提交审批', '确认批复', '标记超支']

interface StatItem {
  label: string
  value: number
  type: 'money' | 'count'
}

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const status = ref('')
const detail = ref<Detail | null>(null)
const caliber = ref('v2')

const stats = ref<StatItem[]>([
  { label: '批复总额', value: 0, type: 'money' },
  { label: '已用金额', value: 0, type: 'money' },
  { label: '剩余额度', value: 0, type: 'money' },
  { label: '超支项目', value: 0, type: 'count' },
])

const caliberLabel = computed(() => (caliber.value === 'v1' ? 'v1（旧口径）' : 'v2（当前口径）'))

/** 表格原始单元格是宽联合类型，金额列统一转数值再展示。 */
function moneyText(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') {
    return '—'
  }
  return formatMoney(Number(value))
}

const detailRows = computed(() => {
  const item = detail.value
  if (!item) return []
  const num = (value: number | null | undefined) => value
  return [
    { label: '资金编号', value: item.资金编号, money: false },
    { label: '费用类别', value: item.费用类别, money: false },
    { label: '项目名称', value: item.项目名称, money: false },
    { label: '批复金额', value: num(item.批复金额), money: true },
    { label: '已用金额', value: num(item.已用金额), money: true },
    { label: '剩余额度', value: num(item.剩余额度), money: true },
    { label: '超支结论', value: item.超支结论, money: false },
    { label: '列支已结算', value: num(item.列支已结算), money: true },
    { label: '列支待结算', value: num(item.列支待结算), money: true },
    { label: '资金状态', value: item.资金状态, money: false },
    { label: '审批人员', value: item.审批人员, money: false },
    { label: '批复留档金额', value: num(item.批复留档金额), money: true },
    { label: '批复口径版本', value: item.批复口径版本, money: false },
    { label: '批复时间', value: item.批复时间, money: false },
  ]
})

function resetFilters() {
  keyword.value = ''
  status.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '资金记录登记入口尚未接入审批流'
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('资金明细读取失败')
    }
    detail.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '资金明细读取失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('养护资金动作未生效，请稍后重试')
    }
    await Promise.all([reload(), loadSummary()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '养护资金操作失败'
  }
}

async function loadSummary() {
  try {
    const response = await request(`${ENDPOINT}/summary`)
    if (!response.ok) {
      return
    }
    const payload = await response.json()
    caliber.value = payload.caliber ?? caliber.value
    stats.value = [
      { label: '批复总额', value: Number(payload.批复总额) || 0, type: 'money' },
      { label: '已用金额', value: Number(payload.已用金额) || 0, type: 'money' },
      { label: '剩余额度', value: Number(payload.剩余额度) || 0, type: 'money' },
      { label: '超支项目', value: Number(payload.超支项目) || 0, type: 'count' },
    ]
  } catch {
    // 汇总读不到时保留上一次的值，不清零
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value) query.set('keyword', keyword.value)
  if (status.value) query.set('status', status.value)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('资金记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '养护资金列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadSummary()
})
</script>

<style scoped>
.money-negative {
  color: #d4380d;
}

.tag-danger {
  color: #d4380d;
  font-weight: 600;
}

.tag-ok {
  color: #389e0d;
}

.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.modal-card {
  background: #fff;
  border-radius: 8px;
  width: 560px;
  max-width: calc(100vw - 32px);
  max-height: calc(100vh - 64px);
  overflow-y: auto;
  padding: 20px 24px;
}

.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.modal-head h3 {
  margin: 0;
  font-size: 16px;
}

.modal-tip {
  margin-top: 12px;
  color: #8c8c8c;
  font-size: 12px;
}
</style>
