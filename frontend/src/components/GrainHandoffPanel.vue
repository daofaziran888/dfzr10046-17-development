<template>
  <section class="handoff-panel" data-testid="grain-handoff-panel">
    <header class="handoff-head">
      <div>
        <h3>声明交接副本（交付凭据）</h3>
        <p class="page-desc">
          出档把声明当日内容冻结成不可变副本，自动在「汇总层派生」派生一单一笔签收待办；
          凭出档号随时下载同一份离线材料。
        </p>
      </div>
      <button class="btn primary" data-testid="open-issue" type="button" @click="openIssue">
        出档交接副本
      </button>
    </header>

    <p v-if="message" class="page-foot" :class="{ 'error-text': !ok }" data-testid="handoff-message">
      {{ message }}
    </p>

    <table class="data-table handoff-table">
      <thead>
        <tr>
          <th>出档号</th>
          <th>声明编号</th>
          <th>修订</th>
          <th>父出档号</th>
          <th>待办状态</th>
          <th>冲突于</th>
          <th>退回原因 / 去向</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="d in dispatches" :key="d.出档号" :data-testid="`dispatch-${d.出档号}`" :data-status="d.待办状态">
          <td>{{ d.出档号 }}</td>
          <td>{{ d.声明编号 }}</td>
          <td>第 {{ d.出档修订 }} 版（{{ d.快照版本 }}）</td>
          <td>{{ d.父出档号 || '—' }}</td>
          <td><span class="status-pill" :data-status="d.待办状态">{{ d.待办状态 }}</span></td>
          <td>{{ d.冲突于 || '—' }}</td>
          <td class="reason-cell">{{ d.退回原因 || d.去向说明 || '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" :data-testid="`download-${d.出档号}`" @click="onDownload(d.出档号)">
              下载材料
            </button>
            <button
              v-if="d.待办状态 === '已退回'"
              class="link"
              type="button"
              :data-testid="`correct-${d.出档号}`"
              @click="openCorrection(d)"
            >
              发起补正
            </button>
            <button class="link" type="button" :data-testid="`edit-${d.声明编号}`" @click="openEdit(d)">
              修订声明
            </button>
          </td>
        </tr>
        <tr v-if="!dispatches.length">
          <td colspan="8" class="empty-state">暂无交接副本，可先出档生成签收待办</td>
        </tr>
      </tbody>
    </table>

    <h4 class="handoff-subhead">补正单（按退回的出档号发起，确认后另发新件并保留父出档号）</h4>
    <table class="data-table handoff-table">
      <thead>
        <tr>
          <th>补正编号</th>
          <th>父出档号</th>
          <th>声明编号</th>
          <th>补正说明</th>
          <th>状态</th>
          <th>新出档号</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="c in corrections" :key="c.补正编号" :data-testid="`correction-${c.补正编号}`">
          <td>{{ c.补正编号 }}</td>
          <td>{{ c.父出档号 }}</td>
          <td>{{ c.声明编号 }}</td>
          <td class="reason-cell">{{ c.补正说明 }}</td>
          <td><span class="status-pill" :data-status="c.status">{{ c.status }}</span></td>
          <td>{{ c.新出档号 || '—' }}</td>
          <td class="row-actions">
            <button
              v-if="c.status === '补正中'"
              class="link"
              type="button"
              :data-testid="`confirm-correction-${c.补正编号}`"
              @click="onConfirmCorrection(c.补正编号)"
            >
              确认补正发新件
            </button>
            <span v-else class="muted-text">已发件</span>
          </td>
        </tr>
        <tr v-if="!corrections.length">
          <td colspan="7" class="empty-state">暂无补正单；汇总员退回出档件后可在此发起补正</td>
        </tr>
      </tbody>
    </table>

    <!-- 出档 -->
    <div v-if="issueOpen" class="modal-backdrop" data-testid="issue-modal">
      <form class="modal" @submit.prevent="submitIssue">
        <h3>出档交接副本</h3>
        <label class="create-field">
          <span>声明编号</span>
          <select v-model="issueDeclareId" data-testid="issue-declare" required>
            <option value="" disabled>请选择粒度声明</option>
            <option v-for="row in declarations" :key="String(row.id)" :value="String(row['声明编号'])">
              {{ row['声明编号'] }}（{{ row['所属事实表'] }}）
            </option>
          </select>
        </label>
        <label class="create-field">
          <span>出档备注（可选）</span>
          <input v-model="issueRemark" data-testid="issue-remark" />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="issueOpen = false">取消</button>
          <button class="btn primary" data-testid="submit-issue" type="submit" :disabled="busy">
            {{ busy ? '提交中…' : '确认出档' }}
          </button>
        </div>
      </form>
    </div>

    <!-- 修订声明（与出档同锁，不拼接两个修订） -->
    <div v-if="editOpen" class="modal-backdrop" data-testid="edit-modal">
      <form class="modal" @submit.prevent="submitEdit">
        <h3>修订粒度声明 {{ editDeclareId }}</h3>
        <p class="page-desc">修订后再出档即生成新出档号；旧出档号材料保持出档当日内容不变。</p>
        <label v-for="field in editableFields" :key="field" class="create-field">
          <span>{{ field }}</span>
          <input v-model="editChanges[field]" :data-testid="`edit-field-${field}`" />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="editOpen = false">取消</button>
          <button class="btn primary" data-testid="submit-edit" type="submit" :disabled="busy">
            {{ busy ? '提交中…' : '保存修订' }}
          </button>
        </div>
      </form>
    </div>

    <!-- 发起补正 -->
    <div v-if="correctionOpen" class="modal-backdrop" data-testid="correction-modal">
      <form class="modal" @submit.prevent="submitCorrection">
        <h3>按出档号 {{ correctionHandoffNo }} 发起补正</h3>
        <p class="page-desc">退回原因：{{ correctionReason || '—' }}。确认补正后将另发新件并保留父出档号。</p>
        <label class="create-field">
          <span>补正说明</span>
          <textarea v-model="correctionNote" data-testid="correction-note" rows="3" required></textarea>
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="correctionOpen = false">取消</button>
          <button class="btn primary" data-testid="submit-correction" type="submit" :disabled="busy">
            {{ busy ? '提交中…' : '发起补正' }}
          </button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import {
  confirmCorrection,
  downloadHandoffMaterial,
  editDeclaration,
  issueDispatch,
  listCorrections,
  listDispatches,
  startCorrection,
} from '@/api/handoff-service'
import { listEntries } from '@/api/backend-service'
import type { Correction, HandoffDispatch } from '@/data/handoff'
import type { EntryRow } from '@/data/types'

const emit = defineEmits<{ (event: 'changed'): void }>()

const editableFields = ['一行代表', '维度组合', '度量可加性', '重复判定键', '声明版本']

const dispatches = ref<HandoffDispatch[]>([])
const corrections = ref<Correction[]>([])
const declarations = ref<EntryRow[]>([])
const message = ref('')
const ok = ref(true)
const busy = ref(false)

const issueOpen = ref(false)
const issueDeclareId = ref('')
const issueRemark = ref('')

const editOpen = ref(false)
const editDeclareId = ref('')
const editChanges = ref<Record<string, string>>({})

const correctionOpen = ref(false)
const correctionHandoffNo = ref('')
const correctionReason = ref('')
const correctionNote = ref('')

function flash(success: boolean, text: string) {
  ok.value = success
  message.value = text
}

async function reload() {
  try {
    const [dispatchPayload, correctionPayload, declarationPayload] = await Promise.all([
      listDispatches(),
      listCorrections(),
      listEntries('grain_declare', {}),
    ])
    dispatches.value = dispatchPayload.items
    corrections.value = correctionPayload.items
    declarations.value = declarationPayload.items
  } catch (error) {
    flash(false, error instanceof Error ? error.message : '交接副本读取失败')
  }
}

async function onConfirmCorrection(correctionNo: string) {
  busy.value = true
  try {
    const result = await confirmCorrection(correctionNo)
    if (!result.ok) throw new Error(result.message)
    flash(true, result.message)
    await reload()
    emit('changed')
  } catch (error) {
    flash(false, error instanceof Error ? error.message : '确认补正失败')
  } finally {
    busy.value = false
  }
}

function openIssue() {
  issueDeclareId.value = declarations.value[0] ? String(declarations.value[0]['声明编号']) : ''
  issueRemark.value = ''
  issueOpen.value = true
}

async function submitIssue() {
  busy.value = true
  try {
    const result = await issueDispatch(issueDeclareId.value, issueRemark.value)
    if (!result.ok) throw new Error(result.message)
    issueOpen.value = false
    flash(true, result.message)
    await reload()
    emit('changed')
  } catch (error) {
    flash(false, error instanceof Error ? error.message : '出档失败')
  } finally {
    busy.value = false
  }
}

function openEdit(dispatch: HandoffDispatch) {
  editDeclareId.value = dispatch.声明编号
  // 用当前生效的声明内容回填，而不是某份可能已过期的出档快照，避免误把旧值写回。
  const live = declarations.value.find((row) => String(row['声明编号']) === dispatch.声明编号)
  const source = live ?? ({} as EntryRow)
  editChanges.value = Object.fromEntries(
    editableFields.map((field) => [field, String(source[field] ?? '')]),
  )
  editOpen.value = true
}

async function submitEdit() {
  const changes = Object.fromEntries(
    Object.entries(editChanges.value).filter(([, value]) => value.trim()),
  )
  if (!Object.keys(changes).length) {
    flash(false, '没有可修订的有效字段')
    return
  }
  busy.value = true
  try {
    const result = await editDeclaration(editDeclareId.value, changes)
    if (!result.ok) throw new Error(result.message)
    editOpen.value = false
    flash(true, result.message)
    await reload()
    emit('changed')
  } catch (error) {
    flash(false, error instanceof Error ? error.message : '修订失败')
  } finally {
    busy.value = false
  }
}

function openCorrection(dispatch: HandoffDispatch) {
  correctionHandoffNo.value = dispatch.出档号
  correctionReason.value = dispatch.退回原因
  correctionNote.value = ''
  correctionOpen.value = true
}

async function submitCorrection() {
  busy.value = true
  try {
    const result = await startCorrection(correctionHandoffNo.value, correctionNote.value)
    if (!result.ok) throw new Error(result.message)
    correctionOpen.value = false
    flash(true, `${result.message}；补正确认后请到补正单清单确认发新件`)
    await reload()
    emit('changed')
  } catch (error) {
    flash(false, error instanceof Error ? error.message : '发起补正失败')
  } finally {
    busy.value = false
  }
}

async function onDownload(handoffNo: string) {
  try {
    await downloadHandoffMaterial(handoffNo)
    flash(true, `已下载出档号 ${handoffNo} 的离线材料`)
  } catch (error) {
    flash(false, error instanceof Error ? error.message : '下载失败')
  }
}

onMounted(reload)
defineExpose({ reload })
</script>
