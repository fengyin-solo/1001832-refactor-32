<template>
  <section class="page">
    <header class="page-head">
      <div>
        <h2>运营概览</h2>
        <p class="page-desc">汇总各业务模块的关键指标，先看总量再看异常。</p>
      </div>
    </header>
    <div class="stat-row">
      <article v-for="card in cards" :key="card.label" class="stat-card">
        <span class="stat-label">{{ card.label }}</span>
        <strong class="stat-value">{{ card.value }}</strong>
      </article>
    </div>

    <h3 class="section-title">养护资金</h3>
    <div class="stat-row">
      <article v-for="card in fundCards" :key="card.label" class="stat-card">
        <span class="stat-label">{{ card.label }}</span>
        <strong class="stat-value" :class="{ 'money-negative': card.money && card.value < 0 }">
          {{ card.money ? formatMoney(card.value) : card.value }}
        </strong>
      </article>
    </div>
    <p class="section-tip">资金卡片与养护资金列表、详情共用同一金额口径（{{ fundCaliber }}），剩余额度保持一致。</p>

    <table class="data-table">
      <thead>
        <tr><th>业务模块</th><th>今日新增</th><th>待处理</th><th>异常量</th></tr>
      </thead>
      <tbody>
        <tr v-for="row in moduleRows" :key="row.name">
          <td>{{ row.name }}</td>
          <td>{{ row.created }}</td>
          <td>{{ row.pending }}</td>
          <td>{{ row.abnormal }}</td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { fetchJson } from '@/api/client'
import { formatMoney } from '@/utils/money'

type FundSummary = {
  批复总额: number
  已用金额: number
  剩余额度: number
  超支项目: number
  caliber: string
}

type Overview = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
  fund?: FundSummary
}

const cards = ref<Overview['cards']>([])
const moduleRows = ref<Overview['modules']>([])
const fund = ref<FundSummary | null>(null)

const fundCaliber = computed(() => (fund.value?.caliber === 'v1' ? 'v1（旧口径）' : 'v2（当前口径）'))
const fundCards = computed(() => {
  const data = fund.value
  if (!data) return []
  return [
    { label: '批复总额', value: data.批复总额, money: true },
    { label: '已用金额', value: data.已用金额, money: true },
    { label: '剩余额度', value: data.剩余额度, money: true },
    { label: '超支项目', value: data.超支项目, money: false },
  ]
})

onMounted(async () => {
  try {
    const payload = await fetchJson<Overview>('/api/overview')
    cards.value = payload.cards
    moduleRows.value = payload.modules
    fund.value = payload.fund ?? null
  } catch {
    cards.value = [{ label: '业务模块', value: 0 }, { label: '今日新增', value: 0 }]
    moduleRows.value = []
  }
})
</script>

<style scoped>
.section-title {
  margin: 24px 0 12px;
  font-size: 15px;
}

.section-tip {
  margin: -4px 0 12px;
  color: #8c8c8c;
  font-size: 12px;
}

.money-negative {
  color: #d4380d;
}
</style>
