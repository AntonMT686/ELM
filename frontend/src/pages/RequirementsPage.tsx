import { ActionIcon, Alert, Anchor, Badge, Button, Card, Checkbox, Code, Drawer, FileInput, Group, Loader, Modal, MultiSelect, Select, SimpleGrid, Stack, Table, Tabs, Text, Textarea, TextInput, Timeline, Tooltip } from '@mantine/core'
import { IconAlertTriangle, IconArrowRight, IconCheck, IconDownload, IconGitBranch, IconGitCompare, IconLink, IconListCheck, IconLock, IconPencil, IconPlus, IconSearch, IconTable, IconTrash, IconUpload, IconX } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { useAction, useProjects, useUsers } from '../api/hooks'
import { EmptyBlock, Hash, Kpi, PageTitle, UserAvatar, When } from '../components/common'
import { UserSelect } from './InboxPage'

const LINK_LABEL: Record<string, string> = { depends_on: 'Depends on', derived_from: 'Derived from', implements: 'Implements', related_to: 'Related to', conflicts_with: 'Conflicts with' }
const REVERSE_LABEL: Record<string, string> = { depends_on: 'Needed by', derived_from: 'Source of', implements: 'Implemented by', related_to: 'Related to', conflicts_with: 'Conflicts with' }
const PRIORITY_COLOR: Record<string, string> = { LOW: 'gray', MEDIUM: 'blue', HIGH: 'orange', CRITICAL: 'red' }
const TYPES = ['FUNCTIONAL', 'NON_FUNCTIONAL', 'INTERFACE', 'PERFORMANCE', 'SAFETY', 'CONSTRAINT', 'SECTION', 'INFORMATION']
const fmt = (s?: string | null) => (s ? dayjs(s).format('DD MMM YYYY') : '—')

function ReqStatus({ status, lifecycle }: { status: string; lifecycle?: any }) {
  const s = lifecycle?.states?.find((x: any) => x.code === status)
  return <Badge size="sm" variant="light" radius="xl" color={s?.color || 'gray'} style={{ textTransform: 'none' }}>{s?.label || status.replace(/_/g, ' ').toLowerCase()}</Badge>
}

export default function RequirementsPage() {
  const { projectId } = useParams()
  const nav = useNavigate()
  const projects = useProjects()
  useEffect(() => { if (!projectId && projects.data?.length === 1) nav(`/requirements/${projects.data[0].id}`, { replace: true }) }, [projectId, projects.data, nav])
  return (
    <div className="page" style={{ maxWidth: 1800 }}>
      <PageTitle icon={<IconListCheck size={22} />} title="Requirements" sub="Capture, review, baseline and trace requirements, from source to tasks and documents."
        extra={<Select w={260} placeholder="Choose a project" searchable value={projectId || null} onChange={(v) => v && nav(`/requirements/${v}`)} allowDeselect={false} data={(projects.data || []).map((p) => ({ value: p.id, label: `${p.code} — ${p.name}` }))} />} />
      {projectId ? <Project key={projectId} projectId={projectId} /> : <EmptyBlock text={projects.data && !projects.data.length ? 'You are not assigned to any project yet.' : 'Choose a project to see its requirements.'} />}
    </div>
  )
}

function Project({ projectId }: { projectId: string }) {
  const [sp, setSp] = useSearchParams()
  const [q, setQ] = useState('')
  const [status, setStatus] = useState<string | null>(null)
  const [priority, setPriority] = useState<string | null>(null)
  const [source, setSource] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const list = useQuery<any>({ queryKey: ['requirements', projectId, q, status, priority, source], queryFn: () => api.get(`/projects/${projectId}/requirements`, { q, status, priority, source_id: source }) })
  const sources = useQuery<any[]>({ queryKey: ['req-sources', projectId], queryFn: () => api.get(`/projects/${projectId}/requirement-sources`) })
  const open = sp.get('open')
  const setOpen = (id: string | null) => { if (id) sp.set('open', id); else sp.delete('open'); setSp(sp, { replace: true }) }
  const d = list.data
  // Show children under their parents; a filter can hide a parent, and its child then shows at the top level.
  const rows = useMemo(() => {
    const items: any[] = d?.items || []
    const ids = new Set(items.map((r) => r.id))
    const kids: Record<string, any[]> = {}
    items.forEach((r) => { if (r.parent_id && ids.has(r.parent_id)) (kids[r.parent_id] ||= []).push(r) })
    const out: any[] = []
    const walk = (r: any, depth: number) => { out.push({ ...r, depth }); (kids[r.id] || []).forEach((k) => walk(k, depth + 1)) }
    items.filter((r) => !r.parent_id || !ids.has(r.parent_id)).forEach((r) => walk(r, 0))
    return out
  }, [d])
  if (list.isError) return <Alert color="red" icon={<IconLock size={16} />}>You do not have access to this project.</Alert>
  return (
    <Tabs defaultValue="register" keepMounted={false}>
      <Tabs.List mb="md">
        <Tabs.Tab value="register" leftSection={<IconListCheck size={15} />}>Register ({d?.items.length ?? '…'})</Tabs.Tab>
        <Tabs.Tab value="rtm" leftSection={<IconTable size={15} />}>Traceability matrix</Tabs.Tab>
        <Tabs.Tab value="baselines" leftSection={<IconLock size={15} />}>Baselines</Tabs.Tab>
        <Tabs.Tab value="sources" leftSection={<IconUpload size={15} />}>Sources and import</Tabs.Tab>
      </Tabs.List>
      <Tabs.Panel value="register">
        <Group mb="sm" justify="space-between">
          <Group gap="xs">
            <TextInput size="xs" w={240} leftSection={<IconSearch size={14} />} placeholder="Search ID or text" value={q} onChange={(e) => setQ(e.currentTarget.value)} />
            <Select size="xs" w={160} placeholder="Any status" clearable value={status} onChange={setStatus} data={(d?.lifecycle?.states || []).map((s: any) => ({ value: s.code, label: s.label }))} />
            <Select size="xs" w={130} placeholder="Any priority" clearable value={priority} onChange={setPriority} data={Object.keys(PRIORITY_COLOR)} />
            <Select size="xs" w={220} placeholder="Any source" clearable value={source} onChange={setSource} data={(sources.data || []).map((s) => ({ value: s.id, label: s.name }))} />
          </Group>
          {d?.can_edit && <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => setCreating(true)}>New requirement</Button>}
        </Group>
        {d && !rows.length ? <EmptyBlock text={q || status || priority || source ? 'No requirement matches these filters.' : 'No requirements yet.'} /> : (
          <Card withBorder p={0} style={{ overflowX: 'auto' }}>
            <Table highlightOnHover verticalSpacing={6} miw={900}>
              <Table.Thead><Table.Tr><Table.Th>Requirement</Table.Th><Table.Th>Status</Table.Th><Table.Th>Rev</Table.Th><Table.Th>Priority</Table.Th><Table.Th>Type</Table.Th><Table.Th>Owner</Table.Th><Table.Th>Source</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>
                {rows.map((r) => (
                  <Table.Tr key={r.id} style={{ cursor: 'pointer' }} onClick={() => setOpen(r.id)}>
                    <Table.Td style={{ paddingLeft: 12 + r.depth * 20 }}><Group gap={8} wrap="nowrap"><Text size="xs" fw={700} c="dimmed" style={{ whiteSpace: 'nowrap' }}>{r.key}</Text><Text size="sm" lineClamp={1}>{r.title}</Text></Group></Table.Td>
                    <Table.Td><ReqStatus status={r.status} lifecycle={d.lifecycle} /></Table.Td>
                    <Table.Td><Text size="xs">{r.revision}</Text></Table.Td>
                    <Table.Td><Badge size="xs" variant="light" color={PRIORITY_COLOR[r.priority]}>{r.priority}</Badge></Table.Td>
                    <Table.Td><Text size="xs" c="dimmed">{r.req_type.replace(/_/g, ' ').toLowerCase()}</Text></Table.Td>
                    <Table.Td>{r.owner ? <UserAvatar user={r.owner} size={22} /> : <Tooltip label="No owner. Choose one before submitting for review."><Badge size="xs" color="orange" variant="outline">None</Badge></Tooltip>}</Table.Td>
                    <Table.Td><Text size="xs" c="dimmed" lineClamp={1} maw={220}>{r.source?.name || '—'}</Text></Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Card>
        )}
      </Tabs.Panel>
      <Tabs.Panel value="rtm"><Rtm projectId={projectId} lifecycle={d?.lifecycle} onOpen={setOpen} /></Tabs.Panel>
      <Tabs.Panel value="baselines"><Baselines projectId={projectId} canBaseline={!!d?.can_baseline} approved={(d?.items || []).filter((r: any) => r.status === 'APPROVED')} /></Tabs.Panel>
      <Tabs.Panel value="sources"><Sources projectId={projectId} canEdit={!!d?.can_edit} sources={sources.data || []} /></Tabs.Panel>
      <EditModal opened={creating} projectId={projectId} sources={sources.data || []} onClose={() => setCreating(false)} onSaved={(r) => { setCreating(false); setOpen(r.id) }} />
      <DetailDrawer id={open} projectId={projectId} sources={sources.data || []} lifecycle={d?.lifecycle} onClose={() => setOpen(null)} onOpen={setOpen} />
    </Tabs>
  )
}

// ------------------------------------------------------------------ create / edit
function EditModal({ opened, value, projectId, sources, onClose, onSaved }: { opened: boolean; value?: any; projectId: string; sources: any[]; onClose: () => void; onSaved: (r: any) => void }) {
  const [f, setF] = useState<any>({})
  useEffect(() => { if (opened) setF(value ? { title: value.title, description: value.description || '', acceptance_criteria: value.acceptance_criteria || '', req_type: value.req_type, priority: value.priority, source_id: value.source?.id || null, parent_id: value.parent?.id || null, owner_id: value.owner?.id || null, org_unit_id: value.org_unit_id, item_id: value.item_id, change_reason: '' } : { title: '', description: '', acceptance_criteria: '', req_type: 'FUNCTIONAL', priority: 'MEDIUM', source_id: sources[0]?.id || null, owner_id: null }) }, [opened, value])
  const set = (k: string) => (v: any) => setF((x: any) => ({ ...x, [k]: v }))
  const released = value && ['APPROVED', 'BASELINED'].includes(value.status)
  const changed = value && (f.title !== value.title || (f.description || '') !== (value.description || '') || (f.acceptance_criteria || '') !== (value.acceptance_criteria || '') || f.req_type !== value.req_type || f.priority !== value.priority)
  const needReason = released && changed
  const save = useAction(() => (value ? api.put(`/requirements/${value.id}`, f, { version: value.version }) : api.post(`/projects/${projectId}/requirements`, f)), { success: 'Requirement saved', invalidate: [['requirements', projectId], ['requirement', value?.id]], onDone: onSaved })
  return (
    <Modal opened={opened} onClose={onClose} size="lg" title={value ? `Edit ${value.key}` : 'New requirement'}>
      <Stack>
        {needReason && <Alert color="orange" p="xs" icon={<IconAlertTriangle size={16} />}>This content is {value.status.toLowerCase()}. Saving opens revision {value.revision + 1} and sends it back to analysis. Revision {value.revision} and any baseline holding it stay as they are, and owners of linked work are told.</Alert>}
        <Textarea label="Title" required autosize minRows={1} value={f.title || ''} onChange={(e) => set('title')(e.currentTarget.value)} />
        <Textarea label="Description" autosize minRows={3} maxRows={10} value={f.description || ''} onChange={(e) => set('description')(e.currentTarget.value)} />
        <Textarea label="Acceptance criteria" autosize minRows={2} maxRows={8} value={f.acceptance_criteria || ''} onChange={(e) => set('acceptance_criteria')(e.currentTarget.value)} />
        <Group grow>
          <Select label="Type" searchable allowDeselect={false} value={f.req_type} onChange={set('req_type')} data={[...new Set([...TYPES, f.req_type].filter(Boolean))]} />
          <Select label="Priority" allowDeselect={false} value={f.priority} onChange={set('priority')} data={Object.keys(PRIORITY_COLOR)} />
        </Group>
        <Select label="Source" clearable value={f.source_id || null} onChange={set('source_id')} data={sources.map((s) => ({ value: s.id, label: s.name }))} description={value ? undefined : 'The source sets the ID prefix.'} />
        <UserSelect label="Owner" value={f.owner_id || null} onChange={set('owner_id')} placeholder={value ? undefined : 'You, if left empty'} />
        {needReason && <Textarea label="Reason for the change" required autosize value={f.change_reason || ''} onChange={(e) => set('change_reason')(e.currentTarget.value)} />}
        <Group justify="flex-end"><Button variant="default" onClick={onClose}>Cancel</Button><Button disabled={(f.title || '').length < 3 || (needReason && !(f.change_reason || '').trim())} loading={save.isPending} onClick={() => save.mutate(undefined)}>Save</Button></Group>
      </Stack>
    </Modal>
  )
}

// ------------------------------------------------------------------ detail
function DetailDrawer({ id, projectId, sources, lifecycle, onClose, onOpen }: { id: string | null; projectId: string; sources: any[]; lifecycle?: any; onClose: () => void; onOpen: (id: string) => void }) {
  const q = useQuery<any>({ queryKey: ['requirement', id], queryFn: () => api.get(`/requirements/${id}`), enabled: !!id })
  const [edit, setEdit] = useState(false)
  const r = q.data
  const keys = [['requirement', id], ['requirements', projectId], ['rtm', projectId], ['req-baselines', projectId]]
  return (
    <Drawer opened={!!id} onClose={onClose} position="right" size={680} title={<Group gap={8}><Text fw={700}>{r?.key || 'Requirement'}</Text>{r && <ReqStatus status={r.status} lifecycle={lifecycle} />}{r && <Badge size="xs" variant="outline" color="gray">Revision {r.revision}</Badge>}</Group>}>
      {q.isLoading && <Group justify="center" py="xl"><Loader type="dots" /></Group>}
      {q.isError && <Alert color="red" icon={<IconAlertTriangle size={16} />}>You cannot open this requirement, or it no longer exists.</Alert>}
      {r && (
        <Stack>
          <div>
            <Group justify="space-between" wrap="nowrap" align="flex-start"><Text fw={650} size="lg" style={{ whiteSpace: 'pre-wrap' }}>{r.title}</Text>{r.can_edit && r.status !== 'UNDER_REVIEW' && <Button size="xs" variant="default" leftSection={<IconPencil size={14} />} onClick={() => setEdit(true)} style={{ flexShrink: 0 }}>Edit</Button>}</Group>
            <Group gap={6} mt={6}>
              <Badge size="xs" variant="light" color={PRIORITY_COLOR[r.priority]}>{r.priority}</Badge>
              <Badge size="xs" variant="light" color="gray">{r.req_type.replace(/_/g, ' ')}</Badge>
              {r.source && <Text size="xs" c="dimmed">{r.source.name}</Text>}
              {r.external_id && <Tooltip label={`ID in ${r.source?.source_system || 'the source system'}${r.external_version ? `, version ${r.external_version}` : ''}`}><Badge size="xs" variant="outline" color="gray">{r.external_id}</Badge></Tooltip>}
            </Group>
          </div>
          <Actions r={r} keys={keys} />
          <Tabs defaultValue="content" keepMounted={false}>
            <Tabs.List>
              <Tabs.Tab value="content">Content</Tabs.Tab>
              <Tabs.Tab value="trace">Traceability ({r.links_out.length + r.links_in.length + r.tasks.length + r.documents.length})</Tabs.Tab>
              <Tabs.Tab value="impact">Impact</Tabs.Tab>
              <Tabs.Tab value="reviews">Reviews ({r.reviews.length})</Tabs.Tab>
              <Tabs.Tab value="history">History</Tabs.Tab>
            </Tabs.List>
            <Tabs.Panel value="content" pt="md"><Content r={r} onOpen={onOpen} /></Tabs.Panel>
            <Tabs.Panel value="trace" pt="md"><Trace r={r} projectId={projectId} keys={keys} onOpen={onOpen} /></Tabs.Panel>
            <Tabs.Panel value="impact" pt="md"><Impact r={r} keys={keys} onOpen={onOpen} /></Tabs.Panel>
            <Tabs.Panel value="reviews" pt="md"><Reviews r={r} /></Tabs.Panel>
            <Tabs.Panel value="history" pt="md"><History r={r} /></Tabs.Panel>
          </Tabs>
          <EditModal opened={edit} value={r} projectId={projectId} sources={sources} onClose={() => setEdit(false)} onSaved={() => setEdit(false)} />
        </Stack>
      )}
    </Drawer>
  )
}

function Actions({ r, keys }: { r: any; keys: any[][] }) {
  const [pending, setPending] = useState<any | null>(null)
  const [reason, setReason] = useState('')
  const [reviewers, setReviewers] = useState<string[]>([])
  const [approvers, setApprovers] = useState<string[]>([])
  const [decision, setDecision] = useState<string | null>(null)
  const [comment, setComment] = useState('')
  const users = useUsers()
  const reset = () => { setPending(null); setReason(''); setReviewers([]); setApprovers([]) }
  const go = useAction((v: any) => api.post(`/requirements/${r.id}/transition`, v, { version: r.version }), { success: 'Status updated', invalidate: keys, onDone: reset })
  const decide = useAction((v: any) => api.post(`/requirements/${r.id}/decision`, v), { success: 'Decision recorded', invalidate: keys, onDone: () => { setDecision(null); setComment('') } })
  const people = (users.data || []).filter((u: any) => u.id !== r.owner?.id).map((u: any) => ({ value: u.id, label: u.full_name }))
  return (
    <Stack gap="xs">
      {r.can_decide && (
        <Alert color="violet" p="xs" title={r.my_review_role === 'APPROVER' ? 'Your approval is requested' : 'Your review is requested'}>
          <Text size="xs" mb={6}>Your decision applies to revision {r.revision} with content hash <Code>{r.content_sha256.slice(0, 12)}…</Code></Text>
          {decision === 'REJECTED' ? (
            <Group align="flex-end" gap="xs"><TextInput style={{ flex: 1 }} size="xs" label="Reason for rejecting" required autoFocus value={comment} onChange={(e) => setComment(e.currentTarget.value)} /><Button size="xs" color="red" disabled={!comment.trim()} loading={decide.isPending} onClick={() => decide.mutate({ decision: 'REJECTED', comment })}>Reject</Button><Button size="xs" variant="subtle" color="gray" onClick={() => setDecision(null)}>Cancel</Button></Group>
          ) : (
            <Group gap="xs"><Button size="xs" color="teal" leftSection={<IconCheck size={14} />} loading={decide.isPending} onClick={() => decide.mutate({ decision: 'APPROVED' })}>{r.my_review_role === 'APPROVER' ? 'Approve' : 'Accept'}</Button><Button size="xs" variant="light" color="red" leftSection={<IconX size={14} />} onClick={() => setDecision('REJECTED')}>Reject</Button></Group>
          )}
        </Alert>
      )}
      {r.waiting_for_reviewers && <Text size="xs" c="dimmed">Your approval opens after all reviewers have decided.</Text>}
      {!!r.transitions.length && (
        <Group gap="xs">{r.transitions.map((t: any) => <Button key={t.to} size="xs" variant="light" rightSection={<IconArrowRight size={14} />} loading={go.isPending && pending?.to === t.to} onClick={() => (t.reason_required || t.to === 'UNDER_REVIEW' ? setPending(t) : (setPending(t), go.mutate({ to: t.to })))}>{t.label}</Button>)}</Group>
      )}
      {pending?.reason_required && (
        <Group align="flex-end" gap="xs"><TextInput style={{ flex: 1 }} size="xs" label={`Reason for “${pending.label}”`} required autoFocus value={reason} onChange={(e) => setReason(e.currentTarget.value)} /><Button size="xs" disabled={!reason.trim()} loading={go.isPending} onClick={() => go.mutate({ to: pending.to, comment: reason })}>Confirm</Button><Button size="xs" variant="subtle" color="gray" onClick={reset}>Cancel</Button></Group>
      )}
      {pending?.to === 'UNDER_REVIEW' && (
        <Card withBorder p="sm">
          <Stack gap="xs">
            <MultiSelect size="xs" label="Reviewers (optional, they decide first)" searchable data={people} value={reviewers} onChange={setReviewers} />
            <MultiSelect size="xs" label="Approvers" required searchable data={people} value={approvers} onChange={setApprovers} description="The owner cannot review or approve their own requirement." />
            <Group justify="flex-end"><Button size="xs" variant="subtle" color="gray" onClick={reset}>Cancel</Button><Button size="xs" disabled={!approvers.length || !!r.submit_blockers.length} loading={go.isPending} onClick={() => go.mutate({ to: 'UNDER_REVIEW', reviewers, approvers })}>Submit for review</Button></Group>
          </Stack>
        </Card>
      )}
      {!!r.submit_blockers.length && <Alert color="orange" p="xs" icon={<IconAlertTriangle size={16} />}><Text size="xs">Before submitting: {r.submit_blockers.join(' ')}</Text></Alert>}
    </Stack>
  )
}

function Block({ label, children }: { label: string; children: any }) {
  return <div><Text size="xs" fw={700} c="dimmed" tt="uppercase" mb={2}>{label}</Text>{children}</div>
}

function Content({ r, onOpen }: { r: any; onOpen: (id: string) => void }) {
  return (
    <Stack>
      <Block label="Description"><Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>{r.description || '—'}</Text></Block>
      <Block label="Acceptance criteria"><Text size="sm" style={{ whiteSpace: 'pre-wrap' }} c={r.acceptance_criteria ? undefined : 'dimmed'}>{r.acceptance_criteria || 'Not written yet.'}</Text></Block>
      <SimpleGrid cols={2}>
        <Block label="Owner">{r.owner ? <UserAvatar user={r.owner} size={22} showName /> : <Text size="sm" c="orange">No owner</Text>}</Block>
        <Block label="Parent">{r.parent ? <Anchor size="sm" onClick={() => onOpen(r.parent.id)}>{r.parent.key}</Anchor> : <Text size="sm">—</Text>}</Block>
      </SimpleGrid>
      <Block label="Content hash"><Hash value={r.content_sha256} /></Block>
      {!!r.children.length && <Block label="Children"><Stack gap={3}>{r.children.map((c: any) => <Group key={c.id} gap={6} wrap="nowrap" style={{ cursor: 'pointer' }} onClick={() => onOpen(c.id)}><Text size="sm" fw={600} style={{ whiteSpace: 'nowrap' }}>{c.key}</Text><Text size="sm" lineClamp={1}>{c.title}</Text></Group>)}</Stack></Block>}
      <Block label="Revisions">
        <Stack gap={4}>{r.revisions.map((v: any) => <Group key={v.revision} gap={8} wrap="nowrap" align="flex-start"><Badge size="xs" variant="light" color="gray" style={{ flexShrink: 0 }}>Rev {v.revision}</Badge><div style={{ minWidth: 0 }}><Text size="sm" lineClamp={2}>{v.title}</Text><Text size="xs" c="dimmed">{fmt(v.created_at)}{v.created_by ? ` · ${v.created_by.full_name}` : ''}{v.change_reason ? ` · ${v.change_reason}` : ''}</Text></div></Group>)}</Stack>
      </Block>
      {!!r.baselines.length && <Block label="In baselines"><Group gap={6}>{r.baselines.map((b: any) => <Tooltip key={b.id} label={b.label}><Badge variant="light" color="teal" size="sm">Baseline {b.seq}, rev {b.revision}</Badge></Tooltip>)}</Group></Block>}
    </Stack>
  )
}

function Trace({ r, projectId, keys, onOpen }: { r: any; projectId: string; keys: any[][]; onOpen: (id: string) => void }) {
  const others = useQuery<any>({ queryKey: ['requirements', projectId, 'pick'], queryFn: () => api.get(`/projects/${projectId}/requirements`) })
  const tasks = useQuery<any[]>({ queryKey: ['work-items', 'project', projectId], queryFn: () => api.get('/work-items', { project_id: projectId, limit: 1000 }) })
  const [docQ, setDocQ] = useState('')
  const docs = useQuery<any>({ queryKey: ['documents', 'pick', projectId, docQ], queryFn: () => api.get('/documents', { q: docQ, project_id: projectId, page_size: 30 }), enabled: r.can_edit })
  const [link, setLink] = useState<{ to: string | null; type: string }>({ to: null, type: 'depends_on' })
  const [task, setTask] = useState<string | null>(null)
  const [doc, setDoc] = useState<string | null>(null)
  const addLink = useAction(() => api.post(`/requirements/${r.id}/links`, { to_id: link.to, link_type: link.type }), { invalidate: keys, onDone: () => setLink({ ...link, to: null }) })
  const delLink = useAction((id: string) => api.del(`/requirements/${r.id}/links/${id}`), { invalidate: keys })
  const addTask = useAction(() => api.post(`/requirements/${r.id}/tasks`, { work_item_id: task }), { invalidate: keys, onDone: () => setTask(null) })
  const delTask = useAction((id: string) => api.del(`/requirements/${r.id}/tasks/${id}`), { invalidate: keys })
  const addDoc = useAction(() => api.post(`/requirements/${r.id}/documents`, { document_id: doc }), { invalidate: keys, onDone: () => setDoc(null) })
  const delDoc = useAction((id: string) => api.del(`/requirements/${r.id}/documents/${id}`), { invalidate: keys })
  const remove = (fn: () => void, label: string) => r.can_edit && <ActionIcon size="sm" variant="subtle" color="red" aria-label={label} onClick={fn}><IconTrash size={14} /></ActionIcon>
  const row = (x: any, label: string, removable: boolean) => (
    <Group key={x.id} justify="space-between" wrap="nowrap">
      <Group gap={6} wrap="nowrap" style={{ minWidth: 0, cursor: 'pointer' }} onClick={() => onOpen(x.req.id)}><Badge size="xs" variant="light" color="gray" style={{ flexShrink: 0 }}>{label}</Badge><Text size="sm" fw={600} style={{ whiteSpace: 'nowrap' }}>{x.req.key}</Text><Text size="sm" lineClamp={1}>{x.req.title}</Text></Group>
      {removable && remove(() => delLink.mutate(x.id), 'Remove link')}
    </Group>
  )
  const linkedTasks = new Set(r.tasks.map((t: any) => t.id))
  return (
    <Stack>
      <Block label="Other requirements">
        <Stack gap={4}>
          {r.links_out.map((x: any) => row(x, LINK_LABEL[x.type] || x.type, true))}
          {r.links_in.map((x: any) => row(x, REVERSE_LABEL[x.type] || x.type, true))}
          {!r.links_out.length && !r.links_in.length && <Text size="sm" c="dimmed">None.</Text>}
        </Stack>
        {r.can_edit && <Group align="flex-end" gap="xs" mt="xs"><Select w={150} size="xs" label="Relation" allowDeselect={false} value={link.type} onChange={(v) => setLink({ ...link, type: v || 'depends_on' })} data={Object.entries(LINK_LABEL).map(([value, label]) => ({ value, label }))} /><Select style={{ flex: 1 }} size="xs" label="Requirement" searchable clearable value={link.to} onChange={(v) => setLink({ ...link, to: v })} data={(others.data?.items || []).filter((x: any) => x.id !== r.id).map((x: any) => ({ value: x.id, label: `${x.key} — ${x.title.slice(0, 60)}` }))} /><Button size="xs" leftSection={<IconLink size={14} />} disabled={!link.to} loading={addLink.isPending} onClick={() => addLink.mutate(undefined)}>Link</Button></Group>}
      </Block>
      <Block label="Tasks">
        <Stack gap={4}>
          {r.tasks.map((t: any) => <Group key={t.link_id} justify="space-between" wrap="nowrap"><Anchor size="sm" lineClamp={1} component={Link} to={`/tasks?open=${t.id}`}><b>{t.key}</b> {t.title}</Anchor><Group gap={6} wrap="nowrap"><Text size="xs" c="dimmed">{Math.round(t.progress)}%</Text>{remove(() => delTask.mutate(t.link_id), 'Remove task link')}</Group></Group>)}
          {!r.tasks.length && <Text size="sm" c="dimmed">None.</Text>}
        </Stack>
        {r.can_edit && <Group align="flex-end" gap="xs" mt="xs"><Select style={{ flex: 1 }} size="xs" label="Add a task" searchable clearable value={task} onChange={setTask} data={(tasks.data || []).filter((t) => !linkedTasks.has(t.id)).map((t) => ({ value: t.id, label: `${t.key} — ${t.title.slice(0, 60)}` }))} /><Button size="xs" disabled={!task} loading={addTask.isPending} onClick={() => addTask.mutate(undefined)}>Link</Button></Group>}
      </Block>
      <Block label="Documents">
        <Stack gap={4}>
          {r.documents.map((d: any) => <Group key={d.link_id} justify="space-between" wrap="nowrap"><Anchor size="sm" lineClamp={1} component={Link} to={`/documents/${d.id}`}><b>{d.number}</b> {d.title}</Anchor>{remove(() => delDoc.mutate(d.link_id), 'Remove document link')}</Group>)}
          {!r.documents.length && <Text size="sm" c="dimmed">None.</Text>}
        </Stack>
        {r.can_edit && <Group align="flex-end" gap="xs" mt="xs"><Select style={{ flex: 1 }} size="xs" label="Add a document" searchable clearable value={doc} onChange={setDoc} onSearchChange={setDocQ} filter={({ options }) => options} nothingFoundMessage="No document found" data={(docs.data?.items || []).map((d: any) => ({ value: d.id, label: `${d.number} — ${d.title.slice(0, 50)}` }))} /><Button size="xs" disabled={!doc} loading={addDoc.isPending} onClick={() => addDoc.mutate(undefined)}>Link</Button></Group>}
      </Block>
    </Stack>
  )
}

function Impact({ r, keys, onOpen }: { r: any; keys: any[][]; onOpen: (id: string) => void }) {
  const q = useQuery<any>({ queryKey: ['requirement-impact', r.id, r.version], queryFn: () => api.get(`/requirements/${r.id}/impact`) })
  const make = useAction(() => api.post(`/requirements/${r.id}/impact-task`), { success: (x: any) => `${x.key} created with ${x.items} item(s) to assess`, invalidate: keys })
  const d = q.data
  if (!d) return null
  const total = d.requirements.length + d.tasks.length + d.documents.length + d.baselines.length
  return (
    <Stack>
      <Text size="sm" c="dimmed">What a change to this requirement could reach. Nothing here changes by itself: a person decides.</Text>
      <Block label={`Dependent requirements (${d.requirements.length})`}><Stack gap={3}>{d.requirements.map((x: any) => <Group key={x.id} gap={6} wrap="nowrap" style={{ cursor: 'pointer' }} onClick={() => onOpen(x.id)}><Badge size="xs" variant="light" color="gray" style={{ flexShrink: 0 }}>{x.because === 'child' ? 'Child' : LINK_LABEL[x.because]}</Badge><Text size="sm" fw={600} style={{ whiteSpace: 'nowrap' }}>{x.key}</Text><Text size="sm" lineClamp={1}>{x.title}</Text></Group>)}{!d.requirements.length && <Text size="sm" c="dimmed">None.</Text>}</Stack></Block>
      {!!d.hidden_requirements && <Alert color="gray" p="xs">{d.hidden_requirements} more dependent requirement(s) are outside your access.</Alert>}
      {!!d.related.length && <Block label="Also linked (not dependent)"><Stack gap={3}>{d.related.map((x: any) => <Text key={x.id} size="sm"><b>{x.key}</b> {x.title}</Text>)}</Stack></Block>}
      <Block label={`Tasks (${d.tasks.length})`}><Stack gap={3}>{d.tasks.map((t: any) => <Anchor key={t.id} size="sm" component={Link} to={`/tasks?open=${t.id}`}><b>{t.key}</b> {t.title}</Anchor>)}{!d.tasks.length && <Text size="sm" c="dimmed">None.</Text>}</Stack></Block>
      <Block label={`Documents (${d.documents.length})`}><Stack gap={3}>{d.documents.map((x: any) => <Anchor key={x.id} size="sm" component={Link} to={`/documents/${x.id}`}><b>{x.number}</b> {x.title}</Anchor>)}{!d.documents.length && <Text size="sm" c="dimmed">None.</Text>}</Stack></Block>
      <Block label={`Baselines (${d.baselines.length})`}><Group gap={6}>{d.baselines.map((b: any) => <Badge key={b.id} variant="light" color="teal" size="sm">{b.seq}: {b.label.slice(0, 40)}</Badge>)}{!d.baselines.length && <Text size="sm" c="dimmed">None.</Text>}</Group></Block>
      {r.can_edit && <Group justify="flex-end"><Button size="xs" variant="light" disabled={!total} loading={make.isPending} onClick={() => make.mutate(undefined)}>Create impact review task</Button></Group>}
    </Stack>
  )
}

function Reviews({ r }: { r: any }) {
  if (!r.reviews.length) return <Text size="sm" c="dimmed">No review has started.</Text>
  const color: Record<string, string> = { APPROVED: 'teal', REJECTED: 'red', PENDING: 'blue', CANCELLED: 'gray' }
  return (
    <Table verticalSpacing={6}>
      <Table.Thead><Table.Tr><Table.Th>Cycle</Table.Th><Table.Th>Rev</Table.Th><Table.Th>Role</Table.Th><Table.Th>Person</Table.Th><Table.Th>Decision</Table.Th><Table.Th>Comment</Table.Th></Table.Tr></Table.Thead>
      <Table.Tbody>{r.reviews.map((x: any) => <Table.Tr key={x.id}><Table.Td>{x.cycle}</Table.Td><Table.Td>{x.revision}</Table.Td><Table.Td><Text size="xs">{x.role.toLowerCase()}</Text></Table.Td><Table.Td><UserAvatar user={x.reviewer} size={22} showName /></Table.Td><Table.Td><Badge size="xs" variant="light" color={color[x.status]}>{x.status.toLowerCase()}</Badge>{x.decided_at && <Text size="xs" c="dimmed">{fmt(x.decided_at)}</Text>}</Table.Td><Table.Td><Text size="xs">{x.comment || ''}</Text></Table.Td></Table.Tr>)}</Table.Tbody>
    </Table>
  )
}

function History({ r }: { r: any }) {
  const label = (e: any) => {
    if (e.kind === 'CREATED') return 'Created'
    if (e.kind === 'IMPORTED') return 'Imported'
    if (e.kind === 'DECISION') return `Decision: ${String(e.to).replace(':', ' ').toLowerCase()}`
    if (e.kind === 'REVISION') return 'New revision after a change'
    if (e.kind === 'BASELINED') return 'Baselined'
    if (e.kind === 'LEGACY_REVIEW') return `PMS: assigned as ${String(e.to).toLowerCase()}`
    if (e.kind === 'LEGACY_STATE') return `PMS: ${e.from} → ${e.to}`
    return `${String(e.from).replace(/_/g, ' ').toLowerCase()} → ${String(e.to).replace(/_/g, ' ').toLowerCase()}`
  }
  return <Timeline bulletSize={14} lineWidth={2}>{r.history.map((e: any) => <Timeline.Item key={e.id} title={<Group gap={6}><Text size="xs" fw={600}>{e.actor?.full_name || 'System'}</Text><When at={e.at} /></Group>}><Text size="sm" c="dimmed">{label(e)}{e.comment ? `. ${e.comment}` : ''}</Text></Timeline.Item>)}</Timeline>
}

// ------------------------------------------------------------------ RTM
function Rtm({ projectId, lifecycle, onOpen }: { projectId: string; lifecycle?: any; onOpen: (id: string) => void }) {
  const q = useQuery<any>({ queryKey: ['rtm', projectId], queryFn: () => api.get(`/projects/${projectId}/rtm`) })
  const [gapsOnly, setGapsOnly] = useState(false)
  const d = q.data
  if (!d) return null
  const s = d.summary
  const pct = (n: number) => (s.total ? `${Math.round((n / s.total) * 100)}% of ${s.total}` : undefined)
  const rows = gapsOnly ? d.rows.filter((r: any) => !r.tasks.length && !r.documents.length && !r.traces_to.length && !r.traced_by.length && !r.designs.length && !r.tests.length) : d.rows
  const RESULT_COLOR: Record<string, string> = { PASSED: 'teal', FAILED: 'red', BLOCKED: 'orange', SKIPPED: 'gray' }
  return (
    <Stack>
      <SimpleGrid cols={{ base: 2, md: 4 }}>
        <Kpi label="Designed" value={s.with_designs} icon={<IconLink size={20} />} color="indigo" hint={pct(s.with_designs)} />
        <Kpi label="With test cases" value={s.with_tests} icon={<IconListCheck size={20} />} color="cyan" hint={pct(s.with_tests)} />
        <Kpi label="Verified (all tests passed)" value={s.verified} icon={<IconLock size={20} />} color="teal" hint={pct(s.verified)} />
        <Kpi label="Linked to tasks" value={s.with_tasks} icon={<IconListCheck size={20} />} color="blue" hint={pct(s.with_tasks)} />
        <Kpi label="Linked to documents" value={s.with_documents} icon={<IconLink size={20} />} color="grape" hint={pct(s.with_documents)} />
        <Kpi label="In a baseline" value={s.baselined} icon={<IconLock size={20} />} color="teal" hint={pct(s.baselined)} />
        <Kpi label="Not traced at all" value={s.untraced} icon={<IconAlertTriangle size={20} />} color={s.untraced ? 'orange' : 'gray'} hint={pct(s.untraced)} />
      </SimpleGrid>
      <Group justify="space-between">
        <Checkbox size="xs" label="Show only untraced requirements" checked={gapsOnly} onChange={(e) => setGapsOnly(e.currentTarget.checked)} />
        <Group gap="xs">{!!s.open_defects && <Text size="xs" c="red">{s.open_defects} requirement(s) have open defects.</Text>}<Button component="a" href={`/api/v1/projects/${projectId}/rtm.csv`} size="xs" variant="default" leftSection={<IconDownload size={14} />}>Export CSV</Button></Group>
      </Group>
      <Card withBorder p={0} style={{ overflow: 'auto', maxHeight: '64vh' }}>
        <Table stickyHeader verticalSpacing={5} miw={1500} highlightOnHover>
          <Table.Thead><Table.Tr><Table.Th>Requirement</Table.Th><Table.Th>Status</Table.Th><Table.Th>Traces to</Table.Th><Table.Th>Traced by</Table.Th><Table.Th>Designs</Table.Th><Table.Th>Tasks</Table.Th><Table.Th>Code</Table.Th><Table.Th>Documents</Table.Th><Table.Th>Tests</Table.Th><Table.Th>Defects</Table.Th><Table.Th>Baselines</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>
            {rows.map((r: any) => (
              <Table.Tr key={r.id} style={{ cursor: 'pointer' }} onClick={() => onOpen(r.id)}>
                <Table.Td maw={380}><Group gap={8} wrap="nowrap"><Text size="xs" fw={700} c="dimmed" style={{ whiteSpace: 'nowrap' }}>{r.key}</Text><Text size="xs" lineClamp={1}>{r.title}</Text></Group></Table.Td>
                <Table.Td><ReqStatus status={r.status} lifecycle={lifecycle} /></Table.Td>
                <Table.Td><Group gap={3}>{r.traces_to.map((t: any, i: number) => <Tooltip key={i} label={LINK_LABEL[t.type] || t.type}><Badge size="xs" variant="outline" color="gray">{t.key}</Badge></Tooltip>)}</Group></Table.Td>
                <Table.Td><Group gap={3}>{r.traced_by.map((t: any, i: number) => <Tooltip key={i} label={REVERSE_LABEL[t.type] || t.type}><Badge size="xs" variant="outline" color="gray">{t.key}</Badge></Tooltip>)}</Group></Table.Td>
                <Table.Td><Group gap={3}>{r.designs.map((x: any) => <Tooltip key={x.id} label={`${x.link_type}${x.section ? ' · ' + x.section : ''} · ${x.status}`}><Badge size="xs" variant="light" color="indigo">{x.key}</Badge></Tooltip>)}</Group></Table.Td>
                <Table.Td><Group gap={3}>{r.tasks.map((t: any) => <Badge key={t.id} size="xs" variant="light" color="blue">{t.key}</Badge>)}</Group></Table.Td>
                <Table.Td><Group gap={3}>{r.code.map((c: any, i: number) => <Badge key={i} size="xs" variant="outline" color={c.state === 'merged' ? 'teal' : 'gray'}>{c.ref}</Badge>)}</Group></Table.Td>
                <Table.Td><Group gap={3}>{r.documents.map((x: any) => <Badge key={x.id} size="xs" variant="light" color="grape">{x.number}</Badge>)}</Group></Table.Td>
                <Table.Td><Group gap={3}>{r.tests.map((t: any) => <Tooltip key={t.id} label={`${t.status} · last result: ${t.last_result || 'not run'}`}><Badge size="xs" variant="light" color={RESULT_COLOR[t.last_result] || 'gray'}>{t.key}</Badge></Tooltip>)}</Group></Table.Td>
                <Table.Td><Group gap={3}>{r.defects.map((x: any) => <Tooltip key={x.id} label={`${x.severity} · ${x.status}`}><Badge size="xs" variant="light" color={['OPEN', 'IN_PROGRESS', 'FIXED'].includes(x.status) ? 'red' : 'gray'}>{x.key}</Badge></Tooltip>)}</Group></Table.Td>
                <Table.Td><Group gap={3}>{r.baselines.map((n: number) => <Badge key={n} size="xs" variant="light" color="teal">{n}</Badge>)}</Group></Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>
    </Stack>
  )
}

// ------------------------------------------------------------------ baselines
function Baselines({ projectId, canBaseline, approved }: { projectId: string; canBaseline: boolean; approved: any[] }) {
  const q = useQuery<any[]>({ queryKey: ['req-baselines', projectId], queryFn: () => api.get(`/projects/${projectId}/requirement-baselines`) })
  const [open, setOpen] = useState(false)
  const [label, setLabel] = useState('')
  const [reason, setReason] = useState('')
  const [picked, setPicked] = useState<string[]>([])
  const [view, setView] = useState<string | null>(null)
  useEffect(() => { if (open) setPicked(approved.map((r) => r.id)) }, [open])
  const make = useAction(() => api.post(`/projects/${projectId}/requirement-baselines`, { label, reason, requirement_ids: picked }), { success: (b: any) => `Baseline ${b.seq} sealed with ${b.items} requirement(s)`, invalidate: [['req-baselines', projectId], ['requirements', projectId], ['rtm', projectId], ['requirement']], onDone: () => { setOpen(false); setLabel(''); setReason('') } })
  return (
    <Stack>
      <Text size="sm" c="dimmed">A baseline is a sealed snapshot of approved requirements. Later changes open new revisions and never alter it.</Text>
      {canBaseline && <Group><Button size="xs" variant="light" leftSection={<IconLock size={14} />} disabled={!approved.length} onClick={() => setOpen(true)}>New baseline</Button>{!approved.length && <Text size="xs" c="dimmed">No approved requirements are waiting.</Text>}</Group>}
      {q.data && !q.data.length && <EmptyBlock text="No baselines yet." icon={<IconGitBranch size={26} />} />}
      {!!q.data?.length && (
        <Card withBorder p={0} style={{ overflowX: 'auto' }}>
          <Table verticalSpacing={8} highlightOnHover miw={760}>
            <Table.Thead><Table.Tr><Table.Th>#</Table.Th><Table.Th>Label</Table.Th><Table.Th>Items</Table.Th><Table.Th>Captured</Table.Th><Table.Th>SHA-256</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>{q.data.map((b) => <Table.Tr key={b.id} style={{ cursor: 'pointer' }} onClick={() => setView(b.id)}><Table.Td>{b.seq}</Table.Td><Table.Td><Text size="sm" fw={600}>{b.label}</Text><Text size="xs" c="dimmed" lineClamp={1}>{b.reason}</Text></Table.Td><Table.Td>{b.items}</Table.Td><Table.Td><Text size="xs">{fmt(b.created_at)}{b.created_by ? ` · ${b.created_by.full_name}` : ''}</Text></Table.Td><Table.Td><Hash value={b.sha256} /></Table.Td></Table.Tr>)}</Table.Tbody>
          </Table>
        </Card>
      )}
      <Modal opened={open} onClose={() => setOpen(false)} title="New requirement baseline" size="lg">
        <Stack>
          <TextInput label="Label" required value={label} onChange={(e) => setLabel(e.currentTarget.value)} />
          <Textarea label="Reason" required autosize minRows={2} value={reason} onChange={(e) => setReason(e.currentTarget.value)} />
          <MultiSelect label="Approved requirements to include" searchable value={picked} onChange={setPicked} data={approved.map((r) => ({ value: r.id, label: `${r.key} — ${r.title.slice(0, 60)}` }))} />
          <Group justify="flex-end"><Button variant="default" onClick={() => setOpen(false)}>Cancel</Button><Button disabled={label.length < 2 || reason.length < 3 || !picked.length} loading={make.isPending} onClick={() => make.mutate(undefined)}>Seal baseline</Button></Group>
        </Stack>
      </Modal>
      <BaselineDrawer id={view} others={(q.data || []).filter((b) => b.id !== view)} onClose={() => setView(null)} />
    </Stack>
  )
}

function BaselineDrawer({ id, others, onClose }: { id: string | null; others: any[]; onClose: () => void }) {
  const [against, setAgainst] = useState<string | null>(null)
  const q = useQuery<any>({ queryKey: ['req-baseline', id], queryFn: () => api.get(`/requirement-baselines/${id}`), enabled: !!id })
  const cmp = useQuery<any>({ queryKey: ['req-baseline-compare', id, against], queryFn: () => api.get(`/requirement-baselines/${id}/compare`, { against }), enabled: !!id })
  useEffect(() => setAgainst(null), [id])
  const d = q.data
  const c = cmp.data
  return (
    <Drawer opened={!!id} onClose={onClose} position="right" size={640} title={<Text fw={700}>Baseline {d?.seq}: {d?.label}</Text>}>
      {d && (
        <Stack>
          <Alert color={d.integrity_ok ? 'teal' : 'red'} p="xs" icon={d.integrity_ok ? <IconLock size={16} /> : <IconAlertTriangle size={16} />}>{d.integrity_ok ? 'The seal is intact: this snapshot has not changed since it was captured.' : 'The seal does not match. This snapshot has been altered.'}</Alert>
          <Text size="sm">{d.reason}</Text>
          <Select size="xs" label="Compare against" leftSection={<IconGitCompare size={14} />} clearable placeholder="Current requirements" value={against} onChange={setAgainst} data={others.map((b) => ({ value: b.id, label: `Baseline ${b.seq}: ${b.label.slice(0, 50)}` }))} />
          {c && (
            <Card withBorder p="sm">
              <Group gap={6} mb={c.changed.length + c.added.length + c.removed.length ? 6 : 0}><Badge size="xs" variant="light" color="orange">{c.changed.length} changed</Badge><Badge size="xs" variant="light" color="teal">{c.added.length} added</Badge><Badge size="xs" variant="light" color="red">{c.removed.length} removed</Badge><Badge size="xs" variant="light" color="gray">{c.unchanged} same</Badge></Group>
              {c.changed.map((x: any) => <Text key={x.key} size="xs" lineClamp={1}><b>{x.key}</b> rev {x.from_revision} → {x.to_revision}: {x.title}</Text>)}
              {c.removed.map((x: any) => <Text key={x.key} size="xs" c="red" lineClamp={1}>− {x.key} {x.title}</Text>)}
              {c.added.slice(0, 30).map((x: any) => <Text key={x.key} size="xs" c="teal" lineClamp={1}>+ {x.key} {x.title}</Text>)}
              {c.added.length > 30 && <Text size="xs" c="dimmed">and {c.added.length - 30} more added.</Text>}
            </Card>
          )}
          <Text fw={650} size="sm">Snapshot ({d.items.length})</Text>
          <Stack gap={6}>{d.items.map((i: any) => <div key={`${i.key}${i.revision}`}><Group gap={6} wrap="nowrap"><Text size="xs" fw={700} style={{ whiteSpace: 'nowrap' }}>{i.key}</Text><Badge size="xs" variant="outline" color="gray">Rev {i.revision}</Badge></Group><Text size="sm" lineClamp={2}>{i.title}</Text></div>)}</Stack>
        </Stack>
      )}
    </Drawer>
  )
}

// ------------------------------------------------------------------ sources and import
function Sources({ projectId, canEdit, sources }: { projectId: string; canEdit: boolean; sources: any[] }) {
  const [creating, setCreating] = useState(false)
  const [f, setF] = useState<any>({ name: '', source_system: 'ELM', external_ref: '', key_prefix: '' })
  const [imp, setImp] = useState<any | null>(null)
  const make = useAction(() => api.post(`/projects/${projectId}/requirement-sources`, f), { success: 'Source added', invalidate: [['req-sources', projectId]], onDone: () => { setCreating(false); setF({ name: '', source_system: 'ELM', external_ref: '', key_prefix: '' }) } })
  return (
    <Stack>
      <Text size="sm" c="dimmed">A source records where requirements came from: a BRD, an SRS or a tool export. It also sets the ID prefix of the requirements it holds.</Text>
      {canEdit && <Group><Button size="xs" variant="light" leftSection={<IconPlus size={14} />} onClick={() => setCreating(true)}>New source</Button></Group>}
      {!sources.length && <EmptyBlock text="No sources yet." />}
      {!!sources.length && (
        <Card withBorder p={0} style={{ overflowX: 'auto' }}>
          <Table verticalSpacing={8} miw={760}>
            <Table.Thead><Table.Tr><Table.Th>Source</Table.Th><Table.Th>System</Table.Th><Table.Th>ID prefix</Table.Th><Table.Th>Requirements</Table.Th><Table.Th>Last import</Table.Th><Table.Th /></Table.Tr></Table.Thead>
            <Table.Tbody>{sources.map((s) => <Table.Tr key={s.id}><Table.Td><Text size="sm" fw={600}>{s.name}</Text>{s.document && <Anchor size="xs" component={Link} to={`/documents/${s.document.id}`}>{s.document.number}</Anchor>}</Table.Td><Table.Td><Badge size="xs" variant="light" color="gray">{s.source_system}</Badge></Table.Td><Table.Td><Code>{s.key_prefix}</Code></Table.Td><Table.Td>{s.requirements}</Table.Td><Table.Td><Text size="xs">{fmt(s.last_synced_at)}{s.external_version ? ` · ${s.external_version}` : ''}</Text></Table.Td><Table.Td ta="right">{canEdit && <Button size="xs" variant="subtle" leftSection={<IconUpload size={14} />} onClick={() => setImp(s)}>Import CSV</Button>}</Table.Td></Table.Tr>)}</Table.Tbody>
          </Table>
        </Card>
      )}
      <Modal opened={creating} onClose={() => setCreating(false)} title="New requirement source">
        <Stack>
          <TextInput label="Name" required value={f.name} onChange={(e) => setF({ ...f, name: e.currentTarget.value })} />
          <Group grow><TextInput label="System" description="For example ELM, DOORS" value={f.source_system} onChange={(e) => setF({ ...f, source_system: e.currentTarget.value })} /><TextInput label="ID prefix" required description="IDs become PREFIX-0001" value={f.key_prefix} onChange={(e) => setF({ ...f, key_prefix: e.currentTarget.value })} /></Group>
          <TextInput label="External reference" value={f.external_ref} onChange={(e) => setF({ ...f, external_ref: e.currentTarget.value })} />
          <Group justify="flex-end"><Button variant="default" onClick={() => setCreating(false)}>Cancel</Button><Button disabled={f.name.length < 2 || f.key_prefix.length < 2} loading={make.isPending} onClick={() => make.mutate(undefined)}>Add source</Button></Group>
        </Stack>
      </Modal>
      <ImportModal source={imp} projectId={projectId} onClose={() => setImp(null)} />
    </Stack>
  )
}

function ImportModal({ source, projectId, onClose }: { source: any | null; projectId: string; onClose: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [version, setVersion] = useState('')
  const [result, setResult] = useState<any | null>(null)
  useEffect(() => { setFile(null); setResult(null); setVersion('') }, [source?.id])
  const send = (dry: boolean) => { const fd = new FormData(); fd.append('file', file as File); fd.append('source_id', source.id); if (version) fd.append('external_version', version); return api.post(`/projects/${projectId}/requirements/import`, fd, { dry_run: dry }) }
  const check = useAction(() => send(true), { onDone: setResult })
  const commit = useAction(() => send(false), { success: (r: any) => `${r.new.length} new and ${r.changed.length} changed requirement(s) imported`, invalidate: [['requirements', projectId], ['req-sources', projectId], ['rtm', projectId]], onDone: onClose })
  const list = (title: string, rows: any[], color: string, note?: string) => !!rows.length && (
    <div><Group gap={6} mb={2}><Badge size="xs" variant="light" color={color}>{rows.length}</Badge><Text size="xs" fw={650}>{title}</Text>{note && <Text size="xs" c="dimmed">{note}</Text>}</Group><Stack gap={0} mah={110} style={{ overflow: 'auto' }}>{rows.map((x, i) => <Text key={i} size="xs" lineClamp={1}>{x.external_id}{x.key ? ` (${x.key})` : ''}{x.title ? `: ${x.title}` : ''}</Text>)}</Stack></div>
  )
  const writes = result ? result.new.length + result.changed.length : 0
  return (
    <Modal opened={!!source} onClose={onClose} size="lg" title={`Import into ${source?.name || ''}`}>
      <Stack>
        <Text size="sm" c="dimmed">Use this for exports from DOORS or any other tool. Needs <Code>external_id</Code> and <Code>title</Code>; optional: <Code>description</Code> <Code>acceptance_criteria</Code> <Code>type</Code> <Code>priority</Code>. You see a preview before anything changes.</Text>
        <Group grow><FileInput label="CSV file" accept=".csv,text/csv" value={file} onChange={(f) => { setFile(f); setResult(null) }} leftSection={<IconUpload size={15} />} clearable /><TextInput label="Source version" value={version} onChange={(e) => setVersion(e.currentTarget.value)} /></Group>
        {result && (
          <Card withBorder p="sm">
            <Stack gap="xs">
              {!!result.errors.length && <Alert color="red" p="xs" title={`${result.errors.length} row(s) have problems. Nothing will be imported until they are fixed.`}><Stack gap={2}>{result.errors.slice(0, 30).map((e: any) => <Text key={e.row} size="xs">Row {e.row}: {e.errors.join(' ')}</Text>)}</Stack></Alert>}
              {list('New', result.new, 'teal')}
              {list('Changed', result.changed, 'blue')}
              {list('Conflicts', result.conflicts, 'orange', 'Approved or under review, so they will not be overwritten')}
              {list('No longer in the file', result.removed, 'red', 'Reported only; they are not deleted')}
              <Text size="xs" c="dimmed">{result.unchanged} unchanged.</Text>
            </Stack>
          </Card>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Cancel</Button>
          <Button variant="light" disabled={!file} loading={check.isPending} onClick={() => check.mutate(undefined)}>Preview</Button>
          <Button disabled={!result || !!result.errors.length || !writes} loading={commit.isPending} onClick={() => commit.mutate(undefined)}>Import {writes || ''} requirement(s)</Button>
        </Group>
      </Stack>
    </Modal>
  )
}
