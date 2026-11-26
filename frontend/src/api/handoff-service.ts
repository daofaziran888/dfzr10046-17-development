/** 粒度声明交接副本接口：出档、签收待办、采用/退回、补正与离线材料下载。 */
import { request } from './client'
import type {
  Correction,
  HandoffDispatch,
  HandoffList,
  HandoffTodo,
} from '@/data/handoff'
import type { ActionResult } from '@/data/types'

const BASE = '/api/grain-handoff'

async function postJson(path: string, body: Record<string, unknown>): Promise<ActionResult> {
  const response = await request(`${BASE}${path}`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
  return (await response.json()) as ActionResult
}

// ---------------------------------------------------------------------------
// 汇总层派生侧：签收待办
// ---------------------------------------------------------------------------
export async function listHandoffTodos(
  declareId = '',
  openOnly = false,
): Promise<HandoffList<HandoffTodo>> {
  const params = new URLSearchParams()
  if (declareId) params.set('declare_id', declareId)
  if (openOnly) params.set('open_only', 'true')
  const response = await request(`${BASE}/todos?${params.toString()}`)
  if (!response.ok) throw new Error('签收待办读取失败')
  return (await response.json()) as HandoffList<HandoffTodo>
}

export const adoptHandoff = (handoffNo: string) =>
  postJson(`/dispatches/${encodeURIComponent(handoffNo)}/adopt`, {})

export const adoptLegacyHandoff = (handoffNo: string) =>
  postJson(`/dispatches/${encodeURIComponent(handoffNo)}/adopt-legacy`, {})

export const switchToNewerHandoff = (handoffNo: string) =>
  postJson(`/dispatches/${encodeURIComponent(handoffNo)}/switch-newer`, {})

export const returnHandoff = (handoffNo: string, reason: string) =>
  postJson(`/dispatches/${encodeURIComponent(handoffNo)}/return`, { reason })

// ---------------------------------------------------------------------------
// 粒度声明侧：出档、补正、下载、修订
// ---------------------------------------------------------------------------
export async function listDispatches(
  declareId = '',
  todoStatus = '',
): Promise<HandoffList<HandoffDispatch>> {
  const params = new URLSearchParams()
  if (declareId) params.set('declare_id', declareId)
  if (todoStatus) params.set('todo_status', todoStatus)
  const response = await request(`${BASE}/dispatches?${params.toString()}`)
  if (!response.ok) throw new Error('交接副本读取失败')
  return (await response.json()) as HandoffList<HandoffDispatch>
}

export const issueDispatch = (declareId: string, remark = '') =>
  postJson('/dispatches', { declare_id: declareId, remark })

export const editDeclaration = (declareId: string, changes: Record<string, string>) =>
  postJson(`/declarations/${encodeURIComponent(declareId)}/edit`, { changes })

export const startCorrection = (handoffNo: string, note: string) =>
  postJson('/corrections/start', { handoff_no: handoffNo, note })

export const confirmCorrection = (correctionNo: string) =>
  postJson(`/corrections/${encodeURIComponent(correctionNo)}/confirm`, {})

export async function listCorrections(handoffNo = ''): Promise<HandoffList<Correction>> {
  const params = new URLSearchParams()
  if (handoffNo) params.set('handoff_no', handoffNo)
  const response = await request(`${BASE}/corrections?${params.toString()}`)
  if (!response.ok) throw new Error('补正单读取失败')
  return (await response.json()) as HandoffList<Correction>
}

/**
 * 凭出档号下载同一份离线 HTML 材料。
 * 响应是出档时渲染并冻结的自包含文件，声明页与汇总页拿到的字节一致。
 */
export async function downloadHandoffMaterial(handoffNo: string): Promise<void> {
  const response = await request(
    `${BASE}/dispatches/${encodeURIComponent(handoffNo)}/material`,
  )
  if (!response.ok) throw new Error('离线材料下载失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${handoffNo}.html`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}
