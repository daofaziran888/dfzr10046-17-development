<template>
  <section class="handoff-panel" data-testid="summary-handoff-panel">
    <header class="handoff-head">
      <div>
        <h3>粒度声明签收待办（汇总层派生）</h3>
        <p class="page-desc">
          每个交接副本派生一单一笔待办，按声明号和出档号采用或退回；
          与声明页共用同一套冲突规则，已采用结果可回查，旧待办必有明确去向。
        </p>
      </div>
      <div class="filter-bar todo-filter">
        <label class="filter-item">
          <span>声明号筛选</span>
          <input v-model="declareFilter" data-testid="todo-filter-declare" placeholder="按声明号检索" @keyup.enter="reload" />
        </label>
        <label class="filter-item check-item">
          <input v-model="openOnly" type="checkbox" data-testid="todo-open-only" @change="reload" />
          <span>只看待办</span>
        </label>
        <button class="btn" data-testid="todo-query" type="button" @click="reload">查询</button>
      </div>
    </header>

    <p v-if="message" class="page-foot" :class="{ 'error-text': !ok }" data-testid="todo-message">
      {{ message }}
    </p>

    <table class="data-table handoff-table">
      <thead>
        <tr>
          <th>出档号</th>
          <th>声明编号</th>
          <th>版本</th>
          <th>父出档号</th>
          <th>待办状态</th>
          <th>冲突 / 去向</th>
          <th>签收操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="todo in todos" :key="todo.出档号" :data-testid="`todo-${todo.出档号}`" :data-status="todo.待办状态">
          <td>{{ todo.出档号 }}</td>
          <td>{{ todo.声明编号 }}</td>
          <td>{{ todo.快照版本 }}（第 {{ todo.出档修订 }} 版）</td>
          <td>{{ todo.父出档号 || '—' }}</td>
          <td><span class="status-pill" :data-status="todo.待办状态">{{ todo.待办状态 }}</span></td>
          <td class="reason-cell">
            <template v-if="todo.待办状态 === '冲突待决'">
              与新出档 <strong>{{ todo.冲突于 }}</strong> 冲突，待选择口径
            </template>
            <template v-else-if="todo.退回原因">退回：{{ todo.退回原因 }}</template>
            <template v-else>{{ todo.去向说明 || '—' }}</template>
          </td>
          <td class="row-actions todo-actions">
            <button class="link" type="button" :data-testid="`todo-download-${todo.出档号}`" @click="onDownload(todo.出档号)">
              离线材料
            </button>
            <button
              v-if="todo.待办状态 === '待签收'"
              class="link"
              type="button"
              :data-testid="`todo-adopt-${todo.出档号}`"
              @click="onAdopt(todo.出档号)"
            >
              采用
            </button>
            <button
              v-if="todo.待办状态 === '待签收'"
              class="link danger"
              type="button"
              :data-testid="`todo-return-${todo.出档号}`"
              @click="openReturn(todo.出档号)"
            >
              退回
            </button>
            <template v-else-if="todo.待办状态 === '冲突待决'">
              <button
                class="link"
                type="button"
                :data-testid="`todo-adopt-legacy-${todo.出档号}`"
                @click="onAdoptLegacy(todo.出档号)"
              >
                采用旧口径
              </button>
              <button
                class="link danger"
                type="button"
                :data-testid="`todo-switch-${todo.出档号}`"
                @click="onSwitch(todo.出档号)"
              >
                回到新副本
              </button>
            </template>
            <span v-else class="muted-text">
              {{ todo.签收人 ? `签收：${todo.签收人}` : '已关闭' }}
            </span>
          </td>
        </tr>
        <tr v-if="!todos.length">
          <td colspan="7" class="empty-state">暂无签收待办</td>
        </tr>
      </tbody>
    </table>

    <!-- 退回登记原因 -->
    <div v-if="returnOpen" class="modal-backdrop" data-testid="return-modal">
      <form class="modal" @submit.prevent="submitReturn">
        <h3>退回出档号 {{ returnHandoffNo }}</h3>
        <label class="create-field">
          <span>退回具体原因（必填）</span>
          <textarea v-model="returnReason" data-testid="return-reason" rows="3" required></textarea>
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="returnOpen = false">取消</button>
          <button class="btn primary" data-testid="submit-return" type="submit" :disabled="busy">
            {{ busy ? '提交中…' : '确认退回' }}
          </button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import {
  adoptHandoff,
  adoptLegacyHandoff,
  downloadHandoffMaterial,
  listHandoffTodos,
  returnHandoff,
  switchToNewerHandoff,
} from '@/api/handoff-service'
import type { HandoffTodo } from '@/data/handoff'

const emit = defineEmits<{ (event: 'changed'): void }>()

const todos = ref<HandoffTodo[]>([])
const declareFilter = ref('')
const openOnly = ref(false)
const message = ref('')
const ok = ref(true)
const busy = ref(false)

const returnOpen = ref(false)
const returnHandoffNo = ref('')
const returnReason = ref('')

function flash(success: boolean, text: string) {
  ok.value = success
  message.value = text
}

async function reload() {
  try {
    const payload = await listHandoffTodos(declareFilter.value.trim(), openOnly.value)
    todos.value = payload.items
  } catch (error) {
    flash(false, error instanceof Error ? error.message : '签收待办读取失败')
  }
}

async function runAction(action: () => Promise<{ ok: boolean; message: string }>, successText?: string) {
  busy.value = true
  try {
    const result = await action()
    if (!result.ok) throw new Error(result.message)
    flash(true, successText ?? result.message)
    await reload()
    emit('changed')
  } catch (error) {
    flash(false, error instanceof Error ? error.message : '操作失败')
  } finally {
    busy.value = false
  }
}

const onAdopt = (handoffNo: string) => runAction(() => adoptHandoff(handoffNo))
const onAdoptLegacy = (handoffNo: string) =>
  runAction(() => adoptLegacyHandoff(handoffNo), `已按旧口径采用 ${handoffNo}，冲突新待办已登记去向`)
const onSwitch = (handoffNo: string) =>
  runAction(() => switchToNewerHandoff(handoffNo), `已回到新副本，旧待办 ${handoffNo} 已登记去向`)

function openReturn(handoffNo: string) {
  returnHandoffNo.value = handoffNo
  returnReason.value = ''
  returnOpen.value = true
}

async function submitReturn() {
  if (!returnReason.value.trim()) {
    flash(false, '退回必须登记具体原因')
    return
  }
  await runAction(
    () => returnHandoff(returnHandoffNo.value, returnReason.value.trim()),
    `出档号 ${returnHandoffNo.value} 已退回并登记原因`,
  )
  returnOpen.value = false
}

async function onDownload(handoffNo: string) {
  try {
    await downloadHandoffMaterial(handoffNo)
    flash(true, `已下载出档号 ${handoffNo} 的离线材料，可离线打开核对`)
  } catch (error) {
    flash(false, error instanceof Error ? error.message : '下载失败')
  }
}

onMounted(reload)
defineExpose({ reload })
</script>
