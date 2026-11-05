import { ActionIcon, Alert, Anchor, Badge, Button, Checkbox, Divider, Drawer, Group, List, Loader, MultiSelect, NumberInput, Progress, Select, Slider, Stack, Tabs, Text, Textarea, TextInput, Timeline, Tooltip } from '@mantine/core'
import { DateInput } from '@mantine/dates'
import { IconAlertTriangle, IconArrowRight, IconCheck, IconLink, IconLock, IconPlus, IconTrash } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { useAction, useMe, useOrgUnits, useUsers } from '../api/hooks'
import { UserSelect } from '../pages/InboxPage'
import { StatusTag, UserAvatar, When } from './common'

export const PRIORITY_COLOR: Record<string, string> = { LOW: 'gray', MEDIUM: 'blue', HIGH: 'orange', CRITICAL: 'red' }
export const KIND_LABEL: Record<string, string> = { TASK: 'Task', ACTION: 'Action item', MILESTONE: 'Milestone', CHANGE_REQUEST: 'Change request', ISSUE: 'Issue' }
const DEP_LABEL: Record<string, string> = { FS: 'Finish → Start', SS: 'Start → Start', FF: 'Finish → Finish', SF: 'Start → Finish' }

const iso = (d: Date | null) => (d ? dayjs(d).format('YYYY-MM-DD') : null)
const toDate = (s?: string | null) => (s ? new Date(s) : null)

/** The fields PUT /work-items accepts. Status is absent on purpose: it only changes through a transition. */
const editable = (w: any) => ({
  title: w.title, description: w.description, kind: w.kind, priority: w.priority, project_id: w.project?.id ?? w.project_id ?? null, item_id: w.item?.id ?? w.item_id ?? null,
  org_unit_id: w.org_unit_id ?? null, document_id: w.document?.id ?? w.document_id ?? null, assignee_id: w.assignee?.id ?? w.assignee_id ?? null,
  plan_id: w.plan?.id ?? w.plan_id ?? null, work_package_id: w.work_package?.id ?? w.work_package_id ?? null, activity_id: w.activity?.id ?? w.activity_id ?? null, milestone_id: w.milestone_id ?? null, parent_id: w.parent_id ?? null,
  start_date: w.start_date ?? null, due_date: w.due_date ?? null, estimated_hours: w.estimated_hours ?? 0, actual_hours: w.actual_hours ?? 0, weight: w.weight ?? null, reported_progress: w.reported_progress ?? 0,
})

export interface TaskTarget { id?: string; defaults?: Record<string, any> }

export default function TaskDrawer({ target, onClose, invalidate = [] }: { target: TaskTarget | null; onClose: () => void; invalidate?: any[][] }) {
  return (
    <Drawer opened={!!target} onClose={onClose} position="right" size={600} title={<Text fw={650}>{target?.id ? 'Task' : 'New task'}</Text>}>
      {target && (target.id ? <Existing key={target.id} id={target.id} onClose={onClose} invalidate={invalidate} /> : <Create defaults={target.defaults} onClose={onClose} invalidate={invalidate} />)}
    </Drawer>
  )
}

function Fields({ f, set, lockProject }: { f: any; set: (k: string) => (v: any) => void; lockProject?: boolean }) {
  const { data: me } = useMe()
  const orgs = useOrgUnits()
  const projects = useQuery<any[]>({ queryKey: ['projects'], queryFn: () => api.get('/projects'), staleTime: 60_000 })
  const known = projects.data?.length ? projects.data : me?.projects || []
  return (
    <Stack gap="sm">
      <TextInput label="Title" required value={f.title || ''} onChange={(e) => set('title')(e.currentTarget.value)} />
      <Group grow>
        <Select label="Kind" value={f.kind} onChange={set('kind')} data={Object.entries(KIND_LABEL).map(([value, label]) => ({ value, label }))} allowDeselect={false} />
        <Select label="Priority" value={f.priority} onChange={set('priority')} data={Object.keys(PRIORITY_COLOR)} allowDeselect={false} />
      </Group>
      <UserSelect label="Owner" value={f.assignee_id || null} onChange={set('assignee_id')} />
      <Group grow>
        <DateInput label="Start" clearable value={toDate(f.start_date)} onChange={(d) => set('start_date')(iso(d))} />
        <DateInput label="Due" clearable value={toDate(f.due_date)} onChange={(d) => set('due_date')(iso(d))} />
      </Group>
      <Group grow>
        <NumberInput label="Estimated hours" min={0} value={f.estimated_hours ?? 0} onChange={(v) => set('estimated_hours')(Number(v) || 0)} />
        <NumberInput label="Actual hours" min={0} value={f.actual_hours ?? 0} onChange={(v) => set('actual_hours')(Number(v) || 0)} />
      </Group>
      <Select label="Project" clearable disabled={lockProject} value={f.project_id || null} onChange={set('project_id')} data={known.map((p: any) => ({ value: p.id, label: p.code }))} description="Leave empty for non-engineering or administrative work" />
      <Select label="Directorate / department" clearable searchable value={f.org_unit_id || null} onChange={set('org_unit_id')} data={(orgs.data || []).map((o) => ({ value: o.id, label: `${o.code} — ${o.name}` }))} />
      <Textarea label="Description" autosize minRows={3} maxRows={10} value={f.description || ''} onChange={(e) => set('description')(e.currentTarget.value)} />
    </Stack>
  )
}

function Create({ defaults, onClose, invalidate }: { defaults?: Record<string, any>; onClose: () => void; invalidate: any[][] }) {
  const { data: me } = useMe()
  const [f, setF] = useState<any>({ kind: 'TASK', priority: 'MEDIUM', assignee_id: me?.user.id, estimated_hours: 0, ...defaults })
  const set = (k: string) => (v: any) => setF((x: any) => ({ ...x, [k]: v }))
  const save = useAction(() => api.post('/work-items', f), { success: 'Task created', invalidate: [['work-items'], ...invalidate], onDone: onClose })
  return (
    <Stack>
      <Fields f={f} set={set} lockProject={!!defaults?.project_id} />
      <Group justify="flex-end"><Button variant="default" onClick={onClose}>Cancel</Button><Button disabled={(f.title || '').length < 3} loading={save.isPending} onClick={() => save.mutate(undefined)}>Create task</Button></Group>
    </Stack>
  )
}

function Existing({ id, onClose, invalidate }: { id: string; onClose: () => void; invalidate: any[][] }) {
  const q = useQuery<any>({ queryKey: ['work-item', id], queryFn: () => api.get(`/work-items/${id}`) })
  const refreshKeys = [['work-item', id], ['work-items'], ...invalidate]
  if (q.isLoading) return <Group justify="center" py="xl"><Loader type="dots" /></Group>
  if (q.isError || !q.data) return <Alert color="red" icon={<IconAlertTriangle size={16} />}>You cannot open this task, or it no longer exists.</Alert>
  const t = q.data
  return (
    <Stack>
      <div>
        <Group gap={8}>
          <Text size="xs" c="dimmed" fw={700}>{t.key}</Text>
          <StatusTag status={t.status} />
          <Badge size="xs" color={PRIORITY_COLOR[t.priority]}>{t.priority}</Badge>
          {t.kind !== 'TASK' && <Badge size="xs" variant="outline" color="grape">{KIND_LABEL[t.kind]}</Badge>}
          {t.legacy_key && <Tooltip label={`Key in the old PMS system${t.legacy_type ? ` (${t.legacy_type})` : ''}`}><Badge size="xs" variant="outline" color="gray">PMS {t.legacy_key}</Badge></Tooltip>}
        </Group>
        <Text fw={650} size="lg" mt={4}>{t.title}</Text>
        <Group gap={6} mt={4}>
          {t.project && <Badge size="xs" variant="light">{t.project.code}</Badge>}
          {t.plan && <Anchor size="xs" component={Link} to={`/planning/${t.project?.id}?plan=${t.plan.id}`}>{t.plan.name}</Anchor>}
          {t.work_package && <Text size="xs" c="dimmed">· {t.work_package.code}</Text>}
          {t.activity && <Text size="xs" c="dimmed">· {t.activity.title}</Text>}
          {t.item && <Badge size="xs" color="violet">{t.item.code}</Badge>}
        </Group>
      </div>
      <div>
        <Group justify="space-between" mb={4}><Text size="xs" c="dimmed">Progress (calculated from status{t.children.length ? ' and sub-tasks' : ''})</Text><Text size="xs" fw={700}>{t.progress}%</Text></Group>
        <Progress value={t.progress} size="sm" color={t.progress >= 100 ? 'teal' : 'blue'} />
      </div>
      <Transitions task={t} keys={refreshKeys} />
      <Tabs defaultValue="details" keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="details">Details</Tabs.Tab>
          <Tabs.Tab value="checklist">Checklist ({t.checklist.length})</Tabs.Tab>
          <Tabs.Tab value="links">Dependencies ({t.predecessors.length + t.successors.length})</Tabs.Tab>
          <Tabs.Tab value="deliverables">Deliverables ({t.deliverables.length})</Tabs.Tab>
          <Tabs.Tab value="people">People</Tabs.Tab>
          <Tabs.Tab value="activity">Activity ({t.comments.length})</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="details" pt="md"><Details task={t} keys={refreshKeys} onClose={onClose} /></Tabs.Panel>
        <Tabs.Panel value="checklist" pt="md"><Checklist task={t} keys={refreshKeys} /></Tabs.Panel>
        <Tabs.Panel value="links" pt="md"><Dependencies task={t} keys={refreshKeys} /></Tabs.Panel>
        <Tabs.Panel value="deliverables" pt="md"><Deliverables task={t} keys={refreshKeys} /></Tabs.Panel>
        <Tabs.Panel value="people" pt="md"><People task={t} keys={refreshKeys} /></Tabs.Panel>
        <Tabs.Panel value="activity" pt="md"><Activity task={t} keys={refreshKeys} /></Tabs.Panel>
      </Tabs>
    </Stack>
  )
}

function Transitions({ task, keys }: { task: any; keys: any[][] }) {
  const [pending, setPending] = useState<any | null>(null)
  const [reason, setReason] = useState('')
  const go = useAction((v: { to: string; comment?: string }) => api.post(`/work-items/${task.id}/transition`, v, { version: task.version }), { success: 'Status updated', invalidate: keys, onDone: () => { setPending(null); setReason('') } })
  if (!task.transitions.length) return <Text size="xs" c="dimmed"><IconLock size={12} /> No status change is available to you right now.</Text>
  const blocked = task.transitions.flatMap((t: any) => t.blockers.map((b: string) => b))
  return (
    <Stack gap="xs">
      <Group gap="xs">
        {task.transitions.map((t: any) => (
          <Tooltip key={t.to} label={t.blockers.join(' · ')} disabled={!t.blockers.length} multiline w={320}>
            <Button size="xs" variant={t.blockers.length ? 'default' : 'light'} rightSection={<IconArrowRight size={14} />} disabled={!!t.blockers.length} loading={go.isPending && pending?.to === t.to}
              onClick={() => (t.reason_required ? setPending(t) : (setPending(t), go.mutate({ to: t.to })))}>{t.label}</Button>
          </Tooltip>
        ))}
      </Group>
      {pending?.reason_required && (
        <Group align="flex-end" gap="xs">
          <TextInput style={{ flex: 1 }} size="xs" label={`Reason for “${pending.label}”`} required autoFocus value={reason} onChange={(e) => setReason(e.currentTarget.value)} />
          <Button size="xs" disabled={!reason.trim()} loading={go.isPending} onClick={() => go.mutate({ to: pending.to, comment: reason })}>Confirm</Button>
          <Button size="xs" variant="subtle" color="gray" onClick={() => setPending(null)}>Cancel</Button>
        </Group>
      )}
      {!!blocked.length && (
        <Alert color="orange" p="xs" icon={<IconAlertTriangle size={16} />} title="Blocked by">
          <List size="xs" spacing={2}>{[...new Set<string>(blocked)].map((b) => <List.Item key={b}>{b}</List.Item>)}</List>
        </Alert>
      )}
    </Stack>
  )
}

function Details({ task, keys, onClose }: { task: any; keys: any[][]; onClose: () => void }) {
  const [f, setF] = useState<any>(editable(task))
  useEffect(() => setF(editable(task)), [task.version])
  const set = (k: string) => (v: any) => setF((x: any) => ({ ...x, [k]: v }))
  const save = useAction(() => api.put(`/work-items/${task.id}`, f, { version: task.version }), { success: 'Task updated', invalidate: keys })
  return (
    <Stack>
      <Fields f={f} set={set} />
      <div>
        <Text size="sm" fw={500} mb={4}>My estimate of progress: {f.reported_progress}%</Text>
        <Slider value={f.reported_progress || 0} onChange={set('reported_progress')} step={5} disabled={!task.can_edit || task.status === 'OPEN'} />
        <Text size="xs" c="dimmed" mt={6}>{task.status === 'OPEN' ? 'Available once the task is started.' : 'Capped at 95% until the task is accepted as completed.'}</Text>
      </div>
      {!!task.children.length && (
        <div>
          <Text size="sm" fw={600} mb={4}>Sub-tasks</Text>
          <Stack gap={4}>{task.children.map((c: any) => <Group key={c.id} justify="space-between" wrap="nowrap"><Text size="sm" lineClamp={1}><b>{c.key}</b> {c.title}</Text><Group gap={6} wrap="nowrap"><StatusTag status={c.status} /><Text size="xs" c="dimmed">{c.progress}%</Text></Group></Group>)}</Stack>
        </div>
      )}
      {!!task.requirements?.length && (
        <div>
          <Text size="sm" fw={600} mb={4}>Requirements</Text>
          <Stack gap={4}>{task.requirements.map((r: any) => <Anchor key={r.id} size="sm" lineClamp={1} component={Link} to={`/requirements/${r.project_id}?open=${r.id}`}><b>{r.key}</b> {r.title}</Anchor>)}</Stack>
        </div>
      )}
      {task.reporter && <Group gap={6}><Text size="xs" c="dimmed">Reported by</Text><UserAvatar user={task.reporter} size={20} /><Text size="xs">{task.reporter.full_name}</Text></Group>}
      <Group justify="flex-end">
        <Button variant="default" onClick={onClose}>Close</Button>
        {task.can_edit && <Button disabled={(f.title || '').length < 3} loading={save.isPending} onClick={() => save.mutate(undefined)}>Save</Button>}
      </Group>
    </Stack>
  )
}

function Checklist({ task, keys }: { task: any; keys: any[][] }) {
  const [text, setText] = useState('')
  const [mandatory, setMandatory] = useState(true)
  const add = useAction(() => api.post(`/work-items/${task.id}/checklist`, { text, mandatory }), { invalidate: keys, onDone: () => setText('') })
  const patch = useAction((v: { id: string; done: boolean }) => api.patch(`/work-items/${task.id}/checklist/${v.id}`, { done: v.done }), { invalidate: keys })
  const del = useAction((id: string) => api.del(`/work-items/${task.id}/checklist/${id}`), { invalidate: keys })
  return (
    <Stack gap="xs">
      {!task.checklist.length && <Text size="sm" c="dimmed">No checklist items. Mandatory items must be ticked before the task can be completed.</Text>}
      {task.checklist.map((i: any) => (
        <Group key={i.id} justify="space-between" wrap="nowrap">
          <Checkbox checked={i.done} disabled={!task.can_edit} onChange={(e) => patch.mutate({ id: i.id, done: e.currentTarget.checked })} label={<>{i.text} {i.mandatory && <Badge size="xs" variant="outline" color="orange">Mandatory</Badge>}</>} description={i.done && i.done_by ? `${i.done_by.full_name}` : undefined} />
          {task.can_manage && <ActionIcon variant="subtle" color="red" aria-label="Remove checklist item" onClick={() => del.mutate(i.id)}><IconTrash size={15} /></ActionIcon>}
        </Group>
      ))}
      {task.can_edit && (
        <Group align="flex-end" gap="xs" mt="xs">
          <TextInput style={{ flex: 1 }} size="xs" placeholder="New checklist item" value={text} onChange={(e) => setText(e.currentTarget.value)} />
          <Checkbox size="xs" label="Mandatory" checked={mandatory} onChange={(e) => setMandatory(e.currentTarget.checked)} />
          <Button size="xs" leftSection={<IconPlus size={14} />} disabled={!text.trim()} onClick={() => add.mutate(undefined)}>Add</Button>
        </Group>
      )}
    </Stack>
  )
}

function Dependencies({ task, keys }: { task: any; keys: any[][] }) {
  const candidates = useQuery<any[]>({ queryKey: ['work-items', 'deps', task.project?.id], queryFn: () => api.get('/work-items', { project_id: task.project?.id, limit: 1000 }), enabled: !!task.project?.id })
  const [pred, setPred] = useState<string | null>(null)
  const [type, setType] = useState<string>('FS')
  const [lag, setLag] = useState<number>(0)
  const add = useAction(() => api.post(`/work-items/${task.id}/dependencies`, { predecessor_id: pred, type, lag_days: lag }), { invalidate: keys, onDone: () => { setPred(null); setLag(0) } })
  const del = useAction((depId: string) => api.del(`/work-items/${task.id}/dependencies/${depId}`), { invalidate: keys })
  const row = (d: any) => (
    <Group key={d.id} justify="space-between" wrap="nowrap">
      <div style={{ minWidth: 0 }}>
        <Group gap={6} wrap="nowrap"><Text size="sm" fw={600}>{d.task.key}</Text><StatusTag status={d.task.status} /><Badge size="xs" variant="light" color="gray">{d.type}{d.lag_days ? ` ${d.lag_days > 0 ? '+' : ''}${d.lag_days}d` : ''}</Badge>{d.cross_directorate && <Badge size="xs" color="pink" variant="light">Cross-directorate</Badge>}</Group>
        <Text size="xs" c="dimmed" lineClamp={1}>{d.task.title}{d.task.assignee ? ` · ${d.task.assignee.full_name}` : ''}</Text>
      </div>
      {task.can_edit && <ActionIcon variant="subtle" color="red" aria-label="Remove dependency" onClick={() => del.mutate(d.id)}><IconTrash size={15} /></ActionIcon>}
    </Group>
  )
  return (
    <Stack gap="sm">
      <Text size="sm" fw={600}>Waits for</Text>
      {task.predecessors.length ? task.predecessors.map(row) : <Text size="sm" c="dimmed">Nothing. This task can start at any time.</Text>}
      <Text size="sm" fw={600} mt="xs">Blocks</Text>
      {task.successors.length ? task.successors.map(row) : <Text size="sm" c="dimmed">No task waits for this one.</Text>}
      {task.can_edit && task.project && (
        <>
          <Divider />
          <Group align="flex-end" gap="xs">
            <Select style={{ flex: 1 }} size="xs" label="Add a predecessor" searchable clearable value={pred} onChange={setPred} data={(candidates.data || []).filter((c) => c.id !== task.id).map((c) => ({ value: c.id, label: `${c.key} — ${c.title.slice(0, 60)}` }))} />
            <Select w={150} size="xs" label="Type" value={type} onChange={(v) => setType(v || 'FS')} allowDeselect={false} data={Object.entries(DEP_LABEL).map(([value, label]) => ({ value, label }))} />
            <NumberInput w={80} size="xs" label="Lag (days)" value={lag} onChange={(v) => setLag(Number(v) || 0)} />
            <Button size="xs" leftSection={<IconLink size={14} />} disabled={!pred} loading={add.isPending} onClick={() => add.mutate(undefined)}>Link</Button>
          </Group>
        </>
      )}
    </Stack>
  )
}

function Deliverables({ task, keys }: { task: any; keys: any[][] }) {
  const [q, setQ] = useState('')
  const docs = useQuery<any>({ queryKey: ['documents', 'pick', task.project?.id, q], queryFn: () => api.get('/documents', { q, project_id: task.project?.id, page_size: 30 }), enabled: task.can_edit })
  const [doc, setDoc] = useState<string | null>(null)
  const [required, setRequired] = useState('RELEASED')
  const add = useAction(() => api.post(`/work-items/${task.id}/deliverables`, { document_id: doc, required_status: required }), { invalidate: keys, onDone: () => setDoc(null) })
  const del = useAction((id: string) => api.del(`/work-items/${task.id}/deliverables/${id}`), { invalidate: keys })
  return (
    <Stack gap="sm">
      {!task.deliverables.length && <Text size="sm" c="dimmed">No deliverables. A mandatory deliverable stops this task being completed until its document reaches the required status.</Text>}
      {task.deliverables.map((d: any) => (
        <Group key={d.id} justify="space-between" wrap="nowrap">
          <div style={{ minWidth: 0 }}>
            <Anchor size="sm" fw={600} component={Link} to={`/documents/${d.document.id}`}>{d.document.number}</Anchor>
            <Text size="xs" c="dimmed" lineClamp={1}>{d.document.title}</Text>
          </div>
          <Group gap={6} wrap="nowrap"><StatusTag status={d.document.status} /><Text size="xs" c="dimmed">needs {d.required_status.toLowerCase()}</Text>{task.can_manage && <ActionIcon variant="subtle" color="red" aria-label="Remove deliverable" onClick={() => del.mutate(d.id)}><IconTrash size={15} /></ActionIcon>}</Group>
        </Group>
      ))}
      {task.can_edit && (
        <Group align="flex-end" gap="xs">
          <Select style={{ flex: 1 }} size="xs" label="Add a document" searchable clearable value={doc} onChange={setDoc} onSearchChange={setQ} filter={({ options }) => options} nothingFoundMessage="No document found" data={(docs.data?.items || []).map((d: any) => ({ value: d.id, label: `${d.number} — ${d.title.slice(0, 50)}` }))} />
          <Select w={130} size="xs" label="Must be" value={required} onChange={(v) => setRequired(v || 'RELEASED')} allowDeselect={false} data={[{ value: 'APPROVED', label: 'Approved' }, { value: 'RELEASED', label: 'Released' }]} />
          <Button size="xs" disabled={!doc} loading={add.isPending} onClick={() => add.mutate(undefined)}>Add</Button>
        </Group>
      )}
    </Stack>
  )
}

function People({ task, keys }: { task: any; keys: any[][] }) {
  const { data: me } = useMe()
  const users = useUsers()
  const [contributors, setContributors] = useState<string[]>(task.contributors.map((u: any) => u.id))
  const [reviewers, setReviewers] = useState<string[]>(task.reviewers.map((u: any) => u.id))
  const save = useAction(() => api.put(`/work-items/${task.id}/participants`, { contributors, reviewers }), { success: 'People updated', invalidate: keys })
  const known = [...task.contributors, ...task.reviewers, ...(users.data || [])]
  const data = [...new Map(known.map((u: any) => [u.id, { value: u.id, label: u.full_name }])).values()]
  const canChange = task.can_manage || task.reporter?.id === me?.user.id
  return (
    <Stack>
      <Group gap={8}><Text size="sm" c="dimmed" w={70}>Owner</Text>{task.assignee ? <UserAvatar user={task.assignee} size={24} showName /> : <Text size="sm" c="dimmed">Unassigned</Text>}</Group>
      <MultiSelect label="Contributors" searchable data={data} value={contributors} onChange={setContributors} disabled={!canChange} />
      <MultiSelect label="Reviewers" description="With a named reviewer, the owner cannot accept their own task." searchable data={data} value={reviewers} onChange={setReviewers} disabled={!canChange} />
      {canChange && <Group justify="flex-end"><Button leftSection={<IconCheck size={15} />} loading={save.isPending} onClick={() => save.mutate(undefined)}>Save people</Button></Group>}
    </Stack>
  )
}

function Activity({ task, keys }: { task: any; keys: any[][] }) {
  const [body, setBody] = useState('')
  const add = useAction(() => api.post(`/work-items/${task.id}/comments`, { body }), { invalidate: keys, onDone: () => setBody('') })
  const items = [
    ...task.comments.map((c: any) => ({ at: c.created_at, who: c.author, node: <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>{c.body}</Text> })),
    ...task.history.map((h: any) => ({ at: h.at, who: h.actor, node: <Text size="sm" c="dimmed">{h.kind === 'CREATED' ? 'Created' : h.kind === 'ASSIGNED' ? 'Reassigned' : h.kind === 'LEGACY_STATE' ? `PMS state: ${h.to}` : `${h.from} → ${h.to}`}{h.comment ? `. ${h.comment}` : ''}</Text> })),
  ].sort((a, b) => (a.at < b.at ? -1 : 1))
  return (
    <Stack>
      <Timeline bulletSize={14} lineWidth={2}>
        {items.map((i, n) => <Timeline.Item key={n} title={<Group gap={6}><Text size="xs" fw={600}>{i.who?.full_name || 'System'}</Text><When at={i.at} /></Group>}>{i.node}</Timeline.Item>)}
      </Timeline>
      <Textarea placeholder="Add a comment" autosize minRows={2} value={body} onChange={(e) => setBody(e.currentTarget.value)} />
      <Group justify="flex-end"><Button size="xs" disabled={!body.trim()} loading={add.isPending} onClick={() => add.mutate(undefined)}>Comment</Button></Group>
    </Stack>
  )
}
