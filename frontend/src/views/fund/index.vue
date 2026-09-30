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
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
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
          <td v-for="column in columns" :key="column">{{ formatCell(column, row[column]) }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">详情</button>
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

    <section v-if="detail" class="detail-panel">
      <header class="detail-head">
        <h3>资金记录详情：{{ detail['资金编号'] }}</h3>
        <button class="btn ghost" type="button" @click="closeDetail">关闭</button>
      </header>
      <dl class="detail-grid">
        <div v-for="field in detailFields" :key="field" class="detail-item">
          <dt>{{ field }}</dt>
          <dd :class="{ 'overrun-text': field === '剩余额度' && detail['是否超支'] }">
            {{ formatCell(field, detail[field]) }}
          </dd>
        </div>
        <div class="detail-item">
          <dt>超支结论</dt>
          <dd :class="{ 'overrun-text': detail['是否超支'] }">{{ detail['是否超支'] ? '已超支' : '未超支' }}</dd>
        </div>
      </dl>
      <h4 class="detail-subtitle">批复留档（批复金额定格在批复当时，不可改写）</h4>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in archiveColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(archive, index) in archivesOf(detail)" :key="index">
            <td v-for="column in archiveColumns" :key="column">{{ formatCell(column, archive[column]) }}</td>
          </tr>
          <tr v-if="!archivesOf(detail).length">
            <td :colspan="archiveColumns.length" class="empty-state">尚未批复，暂无留档记录</td>
          </tr>
        </tbody>
      </table>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 条养护资金记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { fetchJson, request } from '@/api/client'

type ArchiveRecord = Record<string, string | number | null>
type Row = Record<string, string | number | boolean | null | ArchiveRecord[]> & { id?: number }

const ENDPOINT = '/api/fund'
const columns = ["资金编号", "费用类别", "项目名称", "批复金额", "已用金额", "剩余额度", "审批人员", "资金状态"]
const actions = ["提交审批", "确认批复", "标记超支"]
const statuses = ["待审批", "已批复", "执行中", "已超支"]
const amountColumns = new Set(["批复金额", "已用金额", "剩余额度", "批复总额"])
const detailFields = ["资金编号", "费用类别", "项目名称", "批复金额", "已用金额", "剩余额度", "审批人员", "资金状态"]
const archiveColumns = ["留档日期", "批复金额", "已用金额", "剩余额度", "口径版本", "来源"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const stats = ref([
  { label: '批复总额', value: '—' },
  { label: '已用金额', value: '—' },
  { label: '剩余额度', value: '—' },
  { label: '超支项目', value: '—' },
])
const detail = ref<Row | null>(null)

/** 金额展示也收一份：列表、详情、概览卡片都走这个格式，避免各处四舍五入不一致。 */
function formatAmount(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  const amount = Number(value)
  return Number.isNaN(amount) ? '—' : amount.toFixed(2)
}

function formatCell(column: string, value: unknown): string {
  if (amountColumns.has(column)) return formatAmount(value)
  if (value === null || value === undefined || value === '') return '—'
  return String(value)
}

function archivesOf(row: Row | null): ArchiveRecord[] {
  const value = row?.['批复留档']
  return Array.isArray(value) ? value : []
}

function resetFilters() {
  filters.value = {}
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
    detail.value = await fetchJson<Row>(`${ENDPOINT}/${row.id}`)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '资金记录详情读取失败'
  }
}

function closeDetail() {
  detail.value = null
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
    await reload()
    if (detail.value?.id === row.id) {
      await openDetail(row)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '养护资金操作失败'
  }
}

async function loadSummary() {
  try {
    const payload = await fetchJson<Record<string, number>>(`${ENDPOINT}/summary`)
    stats.value = [
      { label: '批复总额', value: formatAmount(payload['批复总额']) },
      { label: '已用金额', value: formatAmount(payload['已用金额']) },
      { label: '剩余额度', value: formatAmount(payload['剩余额度']) },
      { label: '超支项目', value: String(payload['超支项目'] ?? 0) },
    ]
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '资金概览读取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('资金记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    await loadSummary()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '养护资金列表读取失败'
  }
}

onMounted(reload)
</script>
