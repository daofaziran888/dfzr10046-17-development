/** 粒度声明交接副本的前端类型，与后端 app/services/grain_handoff.py 视图对齐。 */

/** 汇总层派生侧的签收待办（每个出档件派生一笔）。 */
export type HandoffTodo = {
  出档号: string
  声明编号: string
  快照版本: string
  出档修订: number
  父出档号: string
  待办状态: string
  冲突于: string
  退回原因: string
  签收人: string
  去向说明: string
  出档时间: string
  决定时间: string
  内容哈希: string
}

/** 粒度声明侧的出档件视图（含快照，不含大块离线材料文本）。 */
export type HandoffDispatch = HandoffTodo & {
  dispatch_status: string
  快照: Record<string, string>
  补正编号: string
  制单员: string
}

export type Correction = {
  id: number
  补正编号: string
  父出档号: string
  声明编号: string
  补正说明: string
  status: string
  新出档号: string
  制单员: string
  创建时间: string
}

export type HandoffList<T> = { items: T[]; total: number }

export const TODO_OPEN_STATUSES = ['待签收', '冲突待决']
