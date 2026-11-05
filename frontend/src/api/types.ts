export interface UserBrief { id: string; username: string; full_name: string; designation?: string; email?: string }
export interface OrgBrief { id: string; code: string; name: string; unit_type: string }

export interface Me {
  user: UserBrief & { employee_no?: string; is_system_admin: boolean }
  orgs: (OrgBrief & { position: string; is_oversight: boolean })[]
  projects: { id: string; code: string; name: string; color?: string }[]
  roles: string[]
  permissions: string[]
  perspective: 'OVERSIGHT' | 'ADMIN' | 'ENGINEER'
  pending_tasks: number
  preferences: Record<string, any>
  settings: { onlyoffice_enabled: boolean; environment: string; app_name: string }
}

export interface DocBrief {
  id: string
  number: string
  title: string
  status: string
  classification: string
  type: { id: string; code: string; name: string; category: string; color?: string; icon?: string }
  project?: { id: string; code: string; name: string } | null
  item?: { id: string; code: string; name: string; level: string; level_name: string } | null
  owner?: UserBrief | null
  owner_org?: OrgBrief | null
  current_revision?: { id: string; label: string; iteration: number; status: string; ext?: string | null } | null
  released_revision?: { id: string; label: string } | null
  updated_at: string
  created_at: string
  version: number
  restricted?: boolean
}

export interface Revision {
  id: string; revision_no: number; label: string; iteration: number; status: string; locked: boolean; sha256?: string
  change_summary?: string; created_at: string; approved_at?: string; released_at?: string; created_by?: UserBrief
  file?: { name: string; extension: string; size: number; mime: string } | null
}

export interface DocFull extends DocBrief {
  description?: string; keywords?: string; external_ref?: string
  domain?: { id: string; code: string; name: string } | null
  current_revision_full?: Revision | null
  revisions: Revision[]
  iterations: { iteration: number; sha256: string; source: string; note?: string; created_at: string; by?: UserBrief; size: number }[]
  relations: { id: string; relation_type: string; direction: 'in' | 'out'; document: DocBrief }[]
  grants: { id: string; user?: UserBrief; org?: OrgBrief; permissions: string[]; valid_to?: string; reason?: string; granted_by: UserBrief }[]
  signatures: { id: string; revision_id: string; signer: UserBrief; role: string; provider: string; algorithm: string; subject: string; serial: string; signed_at: string; sha256: string; status: string; is_cryptographic: boolean }[]
  releases: { id: string; release_no: string; revision_id: string; released_at: string; status: string; by: UserBrief; sha256: string }[]
  active_workflow_id?: string | null
  my_task_id?: string | null
  permissions: { edit: boolean; submit: boolean; revise: boolean; release: boolean; withdraw: boolean; share: boolean; download: boolean; withdraw_submission: boolean }
}

export interface StageView {
  key: string; name: string; type: string; mode: string; checklist: string[]; instructions?: string
  status: string; started_at?: string; ended_at?: string; due_at?: string
  tasks: { id: string; assignee: UserBrief; acted_by?: UserBrief | null; status: string; comment?: string; acted_at?: string; due_at?: string; sha256?: string }[]
}
export interface WorkflowRun {
  id: string; status: string; cycle_no: number; revision: { id: string; label: string }; iteration: number; sha256: string
  current_stage_key?: string; workflow: { name: string; version_no: number }; initiator: UserBrief; started_at: string; completed_at?: string; stages: StageView[]
}

export interface InboxTask {
  id: string; status: string
  stage: { key: string; name: string; type: string; checklist: string[]; instructions?: string; allow_reject: boolean; index: number; count: number }
  stages: { key: string; name: string; type: string }[]
  document: DocBrief
  revision: { id: string; label: string; iteration: number; sha256: string; ext?: string | null }
  initiator: UserBrief; submitted_at: string; cycle_no: number; due_at?: string; overdue: boolean
  delegated_from?: UserBrief | null; acted_at?: string; comment?: string; created_at: string
}

export interface TreeItem {
  id: string; parent_id: string | null; code: string; name: string; part_number?: string
  level: { code: string; name: string; no: number; color?: string; icon?: string }
  lifecycle_phase: string; status: string; lead_org?: OrgBrief | null
  rollup: { counts: Record<string, number>; total: number; released: number; progress: number }
}

export interface Project {
  id: string; code: string; name: string; programme?: string; description?: string; status: string; color?: string
  lead_org?: OrgBrief | null; orgs: (OrgBrief & { participation: string })[]
  levels: { id: string; level_no: number; code: string; name: string; icon?: string; color?: string }[]
  doc_counts?: Record<string, number>; item_count?: number
}

export interface DocType {
  id: string; code: string; name: string; category: string; description?: string; numbering_pattern: string; revision_scheme: string
  allowed_extensions: string; default_template?: string | null; requires_signature: boolean; applicable_levels?: string | null; color?: string; active: boolean
}

export interface Paged<T> { total: number; items: T[]; page?: number; page_size?: number }
