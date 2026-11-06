import { ActionIcon, Alert, Badge, Button, Card, Checkbox, Drawer, FileButton, Group, Loader, Modal, MultiSelect, NumberInput, Progress, Select, SimpleGrid, Stack, Table, Tabs, TagsInput, Text, Textarea, TextInput, Tooltip } from '@mantine/core'
import { IconAlertTriangle, IconBug, IconCheck, IconFlask, IconListCheck, IconLock, IconPaperclip, IconPlayerPlay, IconPlus, IconRobot, IconSend, IconTarget, IconTrash, IconX } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import ArtifactCode from '../components/ArtifactCode'
import { TraceButton } from './TracePage'
import { api } from '../api/client'
import { useAction, useProjects, useUsers } from '../api/hooks'
import { HistoryPanel, LinksPanel, ReasonModal, ReviewPanel, SubmitReviewModal } from '../components/ArtifactParts'
import { EmptyBlock, Hash, Kpi, PageTitle, UserAvatar, When } from '../components/common'

const RESULT_COLOR: Record<string, string> = { PASSED: 'teal', FAILED: 'red', BLOCKED: 'orange', SKIPPED: 'gray', NOT_RUN: 'gray', RETEST: 'violet' }
const CASE_COLOR: Record<string, string> = { DRAFT: 'gray', UNDER_REVIEW: 'violet', APPROVED: 'teal', OBSOLETE: 'gray' }
const PLAN_COLOR: Record<string, string> = { DRAFT: 'gray', UNDER_REVIEW: 'violet', APPROVED: 'cyan', ACTIVE: 'blue', CLOSED: 'gray' }
const SEV_COLOR: Record<string, string> = { LOW: 'gray', MEDIUM: 'blue', HIGH: 'orange', CRITICAL: 'red' }
const TYPES = ['FUNCTIONAL', 'INTEGRATION', 'SYSTEM', 'REGRESSION', 'PERFORMANCE', 'SAFETY', 'SECURITY', 'ACCEPTANCE', 'OTHER']
const label = (s?: string | null) => (s || '').replace(/_/g, ' ').toLowerCase()
const Tag = ({ v, colors }: { v: string; colors: Record<string, string> }) => <Badge size="sm" variant="light" radius="xl" color={colors[v] || 'gray'} style={{ textTransform: 'none' }}>{label(v)}</Badge>

export default function TestingPage() {
  const { projectId } = useParams()
  const nav = useNavigate()
  const projects = useProjects()
  useEffect(() => { if (!projectId && projects.data?.length === 1) nav(`/testing/${projects.data[0].id}`, { replace: true }) }, [projectId, projects.data, nav])
  return (
    <div className="page" style={{ maxWidth: 1700 }}>
      <PageTitle icon={<IconFlask size={22} />} title="Testing and defects" sub="Reviewed test cases, approved plans, runs with evidence, failure analysis and defects, verified by retest."
        extra={<Select w={260} placeholder="Choose a project" searchable value={projectId || null} onChange={(v) => v && nav(`/testing/${v}`)} allowDeselect={false} data={(projects.data || []).map((p) => ({ value: p.id, label: `${p.code} — ${p.name}` }))} />} />
      {projectId ? <Project key={projectId} projectId={projectId} /> : <EmptyBlock text="Choose a project." />}
    </div>
  )
}

function Project({ projectId }: { projectId: string }) {
  const [sp, setSp] = useSearchParams()
  const param = (k: string) => sp.get(k)
  const setParam = (k: string, v: string | null) => { ['case', 'plan', 'run', 'defect'].forEach((x) => sp.delete(x)); if (v) sp.set(k, v); setSp(sp, { replace: true }) }
  const initial = param('run') ? 'runs' : param('defect') ? 'defects' : param('plan') ? 'plans' : 'cases'
  return (
    <>
      <Tabs defaultValue={initial} keepMounted={false}>
        <Tabs.List mb="md">
          <Tabs.Tab value="cases" leftSection={<IconListCheck size={15} />}>Test cases</Tabs.Tab>
          <Tabs.Tab value="plans" leftSection={<IconTarget size={15} />}>Plans</Tabs.Tab>
          <Tabs.Tab value="runs" leftSection={<IconPlayerPlay size={15} />}>Runs</Tabs.Tab>
          <Tabs.Tab value="defects" leftSection={<IconBug size={15} />}>Defects</Tabs.Tab>
          <Tabs.Tab value="coverage" leftSection={<IconCheck size={15} />}>Coverage</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="cases"><Cases projectId={projectId} open={(id) => setParam('case', id)} /></Tabs.Panel>
        <Tabs.Panel value="plans"><Plans projectId={projectId} open={(id) => setParam('plan', id)} /></Tabs.Panel>
        <Tabs.Panel value="runs"><Runs projectId={projectId} open={(id) => setParam('run', id)} /></Tabs.Panel>
        <Tabs.Panel value="defects"><Defects projectId={projectId} open={(id) => setParam('defect', id)} /></Tabs.Panel>
        <Tabs.Panel value="coverage"><Coverage projectId={projectId} /></Tabs.Panel>
      </Tabs>
      <Drawer opened={!!(param('case') || param('plan') || param('run') || param('defect'))} onClose={() => setParam('case', null)} position="right" size={param('run') ? 900 : 720}
        title={<Text fw={650}>{param('case') ? 'Test case' : param('plan') ? 'Test plan' : param('run') ? 'Test run' : 'Defect'}</Text>}>
        {param('case') && <CaseDetail key={param('case')} id={param('case')!} projectId={projectId} />}
        {param('plan') && <PlanDetail key={param('plan')} id={param('plan')!} projectId={projectId} openRun={(id) => setParam('run', id)} />}
        {param('run') && <RunDetail key={param('run')} id={param('run')!} projectId={projectId} openDefect={(id) => setParam('defect', id)} />}
        {param('defect') && <DefectDetail key={param('defect')} id={param('defect')!} projectId={projectId} />}
      </Drawer>
    </>
  )
}

// ------------------------------------------------------------------ cases
function Cases({ projectId, open }: { projectId: string; open: (id: string) => void }) {
  const [q, setQ] = useState('')
  const list = useQuery<any>({ queryKey: ['test-cases', projectId, q], queryFn: () => api.get(`/projects/${projectId}/test-cases`, { q }) })
  const [creating, setCreating] = useState(false)
  if (list.isError) return <Alert color="red" icon={<IconLock size={16} />}>You do not have access to this project.</Alert>
  const d = list.data
  return (
    <>
      <Group mb="sm" justify="space-between">
        <TextInput size="xs" w={260} placeholder="Search ID or title" value={q} onChange={(e) => setQ(e.currentTarget.value)} />
        {d?.can_edit && <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => setCreating(true)}>New test case</Button>}
      </Group>
      <Card withBorder p={0} style={{ overflowX: 'auto' }}>
        <Table highlightOnHover verticalSpacing={6} miw={820}>
          <Table.Thead><Table.Tr><Table.Th>Test case</Table.Th><Table.Th>Type</Table.Th><Table.Th>Status</Table.Th><Table.Th>Rev</Table.Th><Table.Th>Last result</Table.Th><Table.Th>Owner</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>
            {(d?.items || []).map((c: any) => (
              <Table.Tr key={c.id} style={{ cursor: 'pointer' }} onClick={() => open(c.id)}>
                <Table.Td><Group gap={8} wrap="nowrap"><Text size="xs" fw={700} c="dimmed">{c.key}</Text><Text size="sm" lineClamp={1}>{c.title}</Text>{c.automation_id && <Tooltip label={`Automated: ${c.automation_tool || ''} ${c.automation_id}`}><IconRobot size={14} /></Tooltip>}</Group></Table.Td>
                <Table.Td><Text size="xs">{label(c.test_type)}</Text></Table.Td>
                <Table.Td><Tag v={c.status} colors={CASE_COLOR} /></Table.Td>
                <Table.Td><Text size="xs">{c.revision}</Text></Table.Td>
                <Table.Td>{c.last_result ? <Tag v={c.last_result.result} colors={RESULT_COLOR} /> : <Text size="xs" c="dimmed">not run</Text>}</Table.Td>
                <Table.Td>{c.owner && <UserAvatar user={c.owner} size={22} />}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        {d && !d.items.length && <EmptyBlock text="No test cases yet." />}
      </Card>
      {creating && <CaseModal projectId={projectId} onClose={() => setCreating(false)} onSaved={(c) => { setCreating(false); open(c.id) }} />}
    </>
  )
}

function CaseModal({ projectId, value, onClose, onSaved }: { projectId: string; value?: any; onClose: () => void; onSaved: (c: any) => void }) {
  const [f, setF] = useState<any>(value ? { title: value.title, objective: value.objective || '', preconditions: value.preconditions || '', test_type: value.test_type, steps: value.steps, expected_result: value.expected_result || '', automation_id: value.automation_id || '', automation_tool: value.automation_tool || '', reason: '' }
    : { title: '', objective: '', preconditions: '', test_type: 'FUNCTIONAL', steps: [{ action: '', expected: '' }], expected_result: '', automation_id: '', automation_tool: '' })
  const setStep = (i: number, k: string, v: string) => setF({ ...f, steps: f.steps.map((s: any, j: number) => (j === i ? { ...s, [k]: v } : s)) })
  const body = { ...f, steps: f.steps.filter((s: any) => s.action.trim()), automation_id: f.automation_id || null, automation_tool: f.automation_tool || null }
  const save = useAction(() => (value ? api.put(`/test-cases/${value.id}`, body, { version: value.version }) : api.post(`/projects/${projectId}/test-cases`, body)), { success: 'Test case saved', invalidate: [['test-cases', projectId], ['test-case', value?.id]], onDone: onSaved })
  return (
    <Modal opened onClose={onClose} size="xl" title={value ? `Edit ${value.key}` : 'New test case'}>
      <Stack>
        <Group grow><TextInput label="Title" required value={f.title} onChange={(e) => setF({ ...f, title: e.currentTarget.value })} /><Select label="Type" w={180} value={f.test_type} onChange={(v) => setF({ ...f, test_type: v })} data={TYPES} allowDeselect={false} /></Group>
        <Textarea label="Objective" autosize minRows={2} value={f.objective} onChange={(e) => setF({ ...f, objective: e.currentTarget.value })} />
        <Textarea label="Preconditions" autosize minRows={1} value={f.preconditions} onChange={(e) => setF({ ...f, preconditions: e.currentTarget.value })} />
        <Text size="sm" fw={500}>Steps</Text>
        {f.steps.map((s: any, i: number) => (
          <Group key={i} grow align="flex-start" gap="xs">
            <TextInput size="xs" placeholder={`Step ${i + 1}: action`} value={s.action} onChange={(e) => setStep(i, 'action', e.currentTarget.value)} />
            <TextInput size="xs" placeholder="Expected result" value={s.expected} onChange={(e) => setStep(i, 'expected', e.currentTarget.value)} />
            <ActionIcon style={{ flex: 0 }} variant="subtle" color="red" onClick={() => setF({ ...f, steps: f.steps.filter((_: any, j: number) => j !== i) })}><IconTrash size={14} /></ActionIcon>
          </Group>
        ))}
        <Button size="xs" variant="subtle" w={120} onClick={() => setF({ ...f, steps: [...f.steps, { action: '', expected: '' }] })}>Add step</Button>
        <Textarea label="Overall expected result" autosize minRows={1} value={f.expected_result} onChange={(e) => setF({ ...f, expected_result: e.currentTarget.value })} />
        <Group grow><TextInput label="Automation id (optional)" value={f.automation_id} onChange={(e) => setF({ ...f, automation_id: e.currentTarget.value })} /><TextInput label="Automation tool" placeholder="playwright" value={f.automation_tool} onChange={(e) => setF({ ...f, automation_tool: e.currentTarget.value })} /></Group>
        {value?.status === 'APPROVED' && <TextInput label="Reason for changing an approved test case" required value={f.reason} onChange={(e) => setF({ ...f, reason: e.currentTarget.value })} />}
        <Group justify="flex-end"><Button variant="default" onClick={onClose}>Cancel</Button><Button disabled={f.title.length < 3} loading={save.isPending} onClick={() => save.mutate(undefined)}>Save</Button></Group>
      </Stack>
    </Modal>
  )
}

function CaseDetail({ id, projectId }: { id: string; projectId: string }) {
  const q = useQuery<any>({ queryKey: ['test-case', id], queryFn: () => api.get(`/test-cases/${id}`) })
  const keys = [['test-case', id], ['test-cases', projectId], ['rtm', projectId]]
  const [submitting, setSubmitting] = useState(false)
  const [editing, setEditing] = useState(false)
  const [ask, setAsk] = useState<null | 'withdraw' | 'obsolete'>(null)
  const submit = useAction((v: any) => api.post(`/test-cases/${id}/submit`, v), { success: 'Submitted for review', invalidate: keys, onDone: () => setSubmitting(false) })
  const withdraw = useAction((reason: string) => api.post(`/test-cases/${id}/withdraw`, { reason }), { success: 'Withdrawn', invalidate: keys, onDone: () => setAsk(null) })
  const obsolete = useAction((reason: string) => api.post(`/test-cases/${id}/obsolete`, { reason }), { success: 'Made obsolete', invalidate: keys, onDone: () => setAsk(null) })
  if (!q.data) return <Loader type="dots" />
  const c = q.data
  return (
    <Stack>
      <div><Group gap={8}><Text size="xs" c="dimmed" fw={700}>{c.key}</Text><Tag v={c.status} colors={CASE_COLOR} /><Badge size="xs" variant="outline">rev {c.revision}</Badge><Hash value={c.sha256} /></Group><Text fw={650} size="lg" mt={4}>{c.title}</Text></div>
      <Group gap="xs">
        {c.can_edit && c.status === 'DRAFT' && <Button size="xs" leftSection={<IconSend size={14} />} onClick={() => setSubmitting(true)}>Submit for review</Button>}
        {c.can_edit && c.status === 'UNDER_REVIEW' && <Button size="xs" variant="default" onClick={() => setAsk('withdraw')}>Withdraw</Button>}
        {c.can_edit && !['UNDER_REVIEW', 'OBSOLETE'].includes(c.status) && <Button size="xs" variant="default" onClick={() => setEditing(true)}>Edit</Button>}
        {c.status !== 'OBSOLETE' && <Button size="xs" variant="subtle" color="gray" onClick={() => setAsk('obsolete')}>Make obsolete</Button>}
        <TraceButton type="TEST_CASE" id={id} />
      </Group>
      <Tabs defaultValue="content" keepMounted={false}>
        <Tabs.List><Tabs.Tab value="content">Content</Tabs.Tab><Tabs.Tab value="reviews">Review ({c.reviews.length})</Tabs.Tab><Tabs.Tab value="links">Traceability ({c.links.length})</Tabs.Tab><Tabs.Tab value="runs">Runs ({c.runs.length})</Tabs.Tab><Tabs.Tab value="code">Code</Tabs.Tab><Tabs.Tab value="history">History</Tabs.Tab></Tabs.List>
        <Tabs.Panel value="content" pt="md">
          <Stack gap="xs">
            {c.objective && <div><Text size="xs" c="dimmed">Objective</Text><Text size="sm">{c.objective}</Text></div>}
            {c.preconditions && <div><Text size="xs" c="dimmed">Preconditions</Text><Text size="sm">{c.preconditions}</Text></div>}
            <Table fz="sm"><Table.Thead><Table.Tr><Table.Th w={30}>#</Table.Th><Table.Th>Action</Table.Th><Table.Th>Expected</Table.Th></Table.Tr></Table.Thead><Table.Tbody>{c.steps.map((s: any, i: number) => <Table.Tr key={i}><Table.Td>{i + 1}</Table.Td><Table.Td>{s.action}</Table.Td><Table.Td>{s.expected}</Table.Td></Table.Tr>)}</Table.Tbody></Table>
            <Text size="xs" c="dimmed">Revisions: {c.revisions.map((r: any) => `${r.revision}${r.reason ? ` (${r.reason})` : ''}`).join(' · ')}</Text>
          </Stack>
        </Tabs.Panel>
        <Tabs.Panel value="reviews" pt="md"><ReviewPanel reviews={c.reviews} decideUrl={(rid) => `/test-cases/${id}/reviews/${rid}/decide`} keys={keys} /></Tabs.Panel>
        <Tabs.Panel value="links" pt="md"><LinksPanel links={c.links} projectId={projectId} addUrl={`/test-cases/${id}/links`} removeUrl={(lid) => `/test-cases/${id}/links/${lid}`} keys={keys} canEdit={c.can_edit} types={['REQUIREMENT', 'DESIGN', 'TASK']} linkTypes={['verifies', 'related_to', 'implements']} /></Tabs.Panel>
        <Tabs.Panel value="runs" pt="md"><Stack gap={4}>{c.runs.map((r: any, i: number) => <Group key={i} gap="xs"><Text size="sm" fw={600}>{r.run.key}</Text><Text size="sm">{r.run.title}</Text><Tag v={r.status} colors={RESULT_COLOR} /><Text size="xs" c="dimmed">rev {r.revision}</Text></Group>)}{!c.runs.length && <Text size="sm" c="dimmed">Not in any run yet.</Text>}</Stack></Tabs.Panel>
        <Tabs.Panel value="code" pt="md"><ArtifactCode type="TEST_CASE" id={id} /></Tabs.Panel>
        <Tabs.Panel value="history" pt="md"><HistoryPanel history={c.history} /></Tabs.Panel>
      </Tabs>
      <SubmitReviewModal opened={submitting} onClose={() => setSubmitting(false)} title={`Submit ${c.key} revision ${c.revision}`} loading={submit.isPending} onSubmit={(v) => submit.mutate(v)} exclude={[c.owner?.id]} />
      <ReasonModal opened={ask === 'withdraw'} title="Withdraw from review" onClose={() => setAsk(null)} loading={withdraw.isPending} onConfirm={(r) => withdraw.mutate(r)} />
      <ReasonModal opened={ask === 'obsolete'} title="Make this test case obsolete" onClose={() => setAsk(null)} loading={obsolete.isPending} onConfirm={(r) => obsolete.mutate(r)} />
      {editing && <CaseModal projectId={projectId} value={c} onClose={() => setEditing(false)} onSaved={() => setEditing(false)} />}
    </Stack>
  )
}

// ------------------------------------------------------------------ plans
function Plans({ projectId, open }: { projectId: string; open: (id: string) => void }) {
  const list = useQuery<any[]>({ queryKey: ['test-plans', projectId], queryFn: () => api.get(`/projects/${projectId}/test-plans`) })
  const [title, setTitle] = useState('')
  const create = useAction(() => api.post(`/projects/${projectId}/test-plans`, { title }), { success: (p: any) => `${p.key} created`, invalidate: [['test-plans', projectId]], onDone: (p: any) => { setTitle(''); open(p.id) } })
  return (
    <Stack>
      <Group gap="xs"><TextInput size="xs" w={320} placeholder="New plan title" value={title} onChange={(e) => setTitle(e.currentTarget.value)} /><Button size="xs" leftSection={<IconPlus size={14} />} disabled={title.length < 3} loading={create.isPending} onClick={() => create.mutate(undefined)}>Create plan</Button></Group>
      <Card withBorder p={0}>
        <Table highlightOnHover verticalSpacing={6}>
          <Table.Thead><Table.Tr><Table.Th>Plan</Table.Th><Table.Th>Status</Table.Th><Table.Th>Build</Table.Th><Table.Th>Environments</Table.Th><Table.Th>Owner</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>{(list.data || []).map((p) => <Table.Tr key={p.id} style={{ cursor: 'pointer' }} onClick={() => open(p.id)}><Table.Td><Group gap={8}><Text size="xs" fw={700} c="dimmed">{p.key}</Text><Text size="sm">{p.title}</Text></Group></Table.Td><Table.Td><Tag v={p.status} colors={PLAN_COLOR} /></Table.Td><Table.Td><Text size="xs">{p.build_version || '—'}</Text></Table.Td><Table.Td><Text size="xs">{p.environments || '—'}</Text></Table.Td><Table.Td>{p.owner && <UserAvatar user={p.owner} size={22} />}</Table.Td></Table.Tr>)}</Table.Tbody>
        </Table>
        {!list.data?.length && <EmptyBlock text="No test plans yet." />}
      </Card>
    </Stack>
  )
}

function PlanDetail({ id, projectId, openRun }: { id: string; projectId: string; openRun: (id: string) => void }) {
  const q = useQuery<any>({ queryKey: ['test-plan', id], queryFn: () => api.get(`/test-plans/${id}`) })
  const cases = useQuery<any>({ queryKey: ['test-cases', projectId, ''], queryFn: () => api.get(`/projects/${projectId}/test-cases`) })
  const users = useUsers()
  const keys = [['test-plan', id], ['test-plans', projectId], ['test-runs', projectId]]
  const [f, setF] = useState<any>(null)
  const [submitting, setSubmitting] = useState(false)
  const [add, setAdd] = useState<string[]>([])
  const [run, setRun] = useState<any>(null)
  useEffect(() => { if (q.data) setF({ title: q.data.title, scope: q.data.scope || '', build_version: q.data.build_version || '', environments: q.data.environments || '', entry_criteria: q.data.entry_criteria, exit_criteria: q.data.exit_criteria, reason: '' }) }, [q.data?.version])
  const save = useAction(() => api.put(`/test-plans/${id}`, f, { version: q.data.version }), { success: 'Plan saved', invalidate: keys })
  const submit = useAction((v: any) => api.post(`/test-plans/${id}/submit`, v), { success: 'Submitted for approval', invalidate: keys, onDone: () => setSubmitting(false) })
  const activate = useAction(() => api.post(`/test-plans/${id}/activate`), { success: 'Plan activated', invalidate: keys })
  const addCases = useAction((suite: string) => api.post(`/test-suites/${suite}/cases`, { case_ids: add }), { success: 'Cases added', invalidate: keys, onDone: () => setAdd([]) })
  const removeCase = useAction((v: { suite: string; c: string }) => api.del(`/test-suites/${v.suite}/cases/${v.c}`), { invalidate: keys })
  const newRun = useAction(() => api.post(`/test-plans/${id}/runs`, run), { success: (r: any) => `${r.key} created`, invalidate: keys, onDone: (r: any) => { setRun(null); openRun(r.id) } })
  if (!q.data || !f) return <Loader type="dots" />
  const p = q.data
  const editable = p.can_edit && !['UNDER_REVIEW', 'CLOSED'].includes(p.status)
  const ex = f.exit_criteria
  return (
    <Stack>
      <div><Group gap={8}><Text size="xs" c="dimmed" fw={700}>{p.key}</Text><Tag v={p.status} colors={PLAN_COLOR} /><Badge size="xs" variant="outline">rev {p.revision}</Badge><Hash value={p.sha256} /></Group><Text fw={650} size="lg" mt={4}>{p.title}</Text></div>
      <Group gap="xs">
        {p.can_edit && p.status === 'DRAFT' && <Button size="xs" leftSection={<IconSend size={14} />} onClick={() => setSubmitting(true)}>Submit for approval</Button>}
        {p.can_approve && p.status === 'APPROVED' && <Button size="xs" color="teal" onClick={() => activate.mutate(undefined)}>Activate</Button>}
        {p.status === 'ACTIVE' && <Button size="xs" leftSection={<IconPlayerPlay size={14} />} onClick={() => setRun({ title: `Run ${p.runs.length + 1}`, build_version: p.build_version || '', environment: '' })}>New run</Button>}
      </Group>
      <Tabs defaultValue="scope" keepMounted={false}>
        <Tabs.List><Tabs.Tab value="scope">Scope and criteria</Tabs.Tab><Tabs.Tab value="suites">Suites</Tabs.Tab><Tabs.Tab value="runs">Runs ({p.runs.length})</Tabs.Tab><Tabs.Tab value="reviews">Approval ({p.reviews.length})</Tabs.Tab><Tabs.Tab value="history">History</Tabs.Tab></Tabs.List>
        <Tabs.Panel value="scope" pt="md">
          <Stack gap="xs">
            <TextInput label="Title" disabled={!editable} value={f.title} onChange={(e) => setF({ ...f, title: e.currentTarget.value })} />
            <Textarea label="Scope" disabled={!editable} autosize minRows={2} value={f.scope} onChange={(e) => setF({ ...f, scope: e.currentTarget.value })} />
            <Group grow><TextInput label="Build / version" disabled={!editable} value={f.build_version} onChange={(e) => setF({ ...f, build_version: e.currentTarget.value })} /><TextInput label="Environments" disabled={!editable} value={f.environments} onChange={(e) => setF({ ...f, environments: e.currentTarget.value })} /></Group>
            <TagsInput label="Entry criteria" disabled={!editable} value={f.entry_criteria} onChange={(v) => setF({ ...f, entry_criteria: v })} />
            <Text size="sm" fw={600}>Exit criteria</Text>
            <Group>
              <Checkbox disabled={!editable} label="Every case executed" checked={!!ex.all_executed} onChange={(e) => setF({ ...f, exit_criteria: { ...ex, all_executed: e.currentTarget.checked } })} />
              <NumberInput disabled={!editable} w={170} size="xs" label="Minimum pass rate %" min={0} max={100} value={ex.min_pass_rate ?? 100} onChange={(v) => setF({ ...f, exit_criteria: { ...ex, min_pass_rate: Number(v) } })} />
              <MultiSelect disabled={!editable} w={260} size="xs" label="No open defects of severity" data={['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']} value={ex.no_open_defects || []} onChange={(v) => setF({ ...f, exit_criteria: { ...ex, no_open_defects: v } })} />
            </Group>
            <TagsInput label="Manual exit checks (confirmed at closure)" disabled={!editable} value={ex.manual || []} onChange={(v) => setF({ ...f, exit_criteria: { ...ex, manual: v } })} />
            {['APPROVED', 'ACTIVE'].includes(p.status) && editable && <TextInput label="Reason for changing an approved plan" value={f.reason} onChange={(e) => setF({ ...f, reason: e.currentTarget.value })} />}
            {editable && <Group justify="flex-end"><Button size="xs" loading={save.isPending} onClick={() => save.mutate(undefined)}>Save plan</Button></Group>}
          </Stack>
        </Tabs.Panel>
        <Tabs.Panel value="suites" pt="md">
          <Stack>
            {p.suites.map((s: any) => (
              <Card key={s.id} withBorder>
                <Text fw={600} size="sm" mb="xs">{s.name} ({s.cases.length})</Text>
                <Stack gap={4}>{s.cases.map((c: any) => <Group key={c.id} justify="space-between"><Group gap={6}><Text size="sm" fw={600}>{c.key}</Text><Text size="sm">{c.title}</Text><Tag v={c.status} colors={CASE_COLOR} /></Group>{editable && <ActionIcon size="sm" variant="subtle" color="red" onClick={() => removeCase.mutate({ suite: s.id, c: c.id })}><IconTrash size={14} /></ActionIcon>}</Group>)}</Stack>
                {editable && (
                  <Group mt="xs" gap="xs" align="flex-end">
                    <MultiSelect size="xs" style={{ flex: 1 }} placeholder="Add test cases" searchable value={add} onChange={setAdd} data={(cases.data?.items || []).filter((c: any) => c.status !== 'OBSOLETE' && !s.cases.some((x: any) => x.id === c.id)).map((c: any) => ({ value: c.id, label: `${c.key} ${c.title} (${label(c.status)})` }))} />
                    <Button size="xs" disabled={!add.length} onClick={() => addCases.mutate(s.id)}>Add</Button>
                  </Group>
                )}
              </Card>
            ))}
            <Text size="xs" c="dimmed">Only approved test cases can be executed in a run.</Text>
          </Stack>
        </Tabs.Panel>
        <Tabs.Panel value="runs" pt="md"><Stack gap={4}>{p.runs.map((r: any) => <Group key={r.id} gap="xs" style={{ cursor: 'pointer' }} onClick={() => openRun(r.id)}><Text size="sm" fw={600}>{r.key}</Text><Text size="sm">{r.title}</Text><Badge size="xs">{label(r.status)}</Badge><Text size="xs" c="dimmed">{r.build_version}</Text></Group>)}{!p.runs.length && <Text size="sm" c="dimmed">No runs yet.</Text>}</Stack></Tabs.Panel>
        <Tabs.Panel value="reviews" pt="md"><ReviewPanel reviews={p.reviews} decideUrl={(rid) => `/test-plans/${id}/reviews/${rid}/decide`} keys={keys} /></Tabs.Panel>
        <Tabs.Panel value="history" pt="md"><HistoryPanel history={p.history} /></Tabs.Panel>
      </Tabs>
      <SubmitReviewModal opened={submitting} onClose={() => setSubmitting(false)} title={`Submit ${p.key} for approval`} loading={submit.isPending} onSubmit={(v) => submit.mutate(v)} exclude={[p.owner?.id]} />
      <Modal opened={!!run} onClose={() => setRun(null)} title={`New run from ${p.key}`}>
        {run && <Stack>
          <TextInput label="Title" value={run.title} onChange={(e) => setRun({ ...run, title: e.currentTarget.value })} />
          <Group grow><TextInput label="Build / version" value={run.build_version} onChange={(e) => setRun({ ...run, build_version: e.currentTarget.value })} /><TextInput label="Environment" value={run.environment} onChange={(e) => setRun({ ...run, environment: e.currentTarget.value })} /></Group>
          <Select label="Executor" searchable clearable value={run.executor_id || null} onChange={(v) => setRun({ ...run, executor_id: v })} data={(users.data || []).map((u) => ({ value: u.id, label: u.full_name }))} />
          <Text size="xs" c="dimmed">The run takes every approved case in the plan's suites, at its current revision.</Text>
          <Group justify="flex-end"><Button variant="default" onClick={() => setRun(null)}>Cancel</Button><Button loading={newRun.isPending} onClick={() => newRun.mutate(undefined)}>Create run</Button></Group>
        </Stack>}
      </Modal>
    </Stack>
  )
}

// ------------------------------------------------------------------ runs
function Runs({ projectId, open }: { projectId: string; open: (id: string) => void }) {
  const list = useQuery<any[]>({ queryKey: ['test-runs', projectId], queryFn: () => api.get(`/projects/${projectId}/test-runs`) })
  return (
    <Card withBorder p={0}>
      <Table highlightOnHover verticalSpacing={6}>
        <Table.Thead><Table.Tr><Table.Th>Run</Table.Th><Table.Th>Status</Table.Th><Table.Th>Build</Table.Th><Table.Th>Results</Table.Th><Table.Th>Pass rate</Table.Th><Table.Th>Created</Table.Th></Table.Tr></Table.Thead>
        <Table.Tbody>
          {(list.data || []).map((r) => (
            <Table.Tr key={r.id} style={{ cursor: 'pointer' }} onClick={() => open(r.id)}>
              <Table.Td><Group gap={8}><Text size="xs" fw={700} c="dimmed">{r.key}</Text><Text size="sm">{r.title}</Text></Group></Table.Td>
              <Table.Td><Badge size="sm" variant="light">{label(r.status)}</Badge></Table.Td>
              <Table.Td><Text size="xs">{r.build_version}</Text></Table.Td>
              <Table.Td><Group gap={4}>{Object.entries(r.counts).map(([k, v]) => <Badge key={k} size="xs" color={RESULT_COLOR[k]} variant="light">{label(k)} {String(v)}</Badge>)}</Group></Table.Td>
              <Table.Td w={160}><Progress value={r.pass_rate} color="teal" size="sm" /><Text size="xs">{r.pass_rate}% of {r.total}</Text></Table.Td>
              <Table.Td><When at={r.created_at} /></Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      {!list.data?.length && <EmptyBlock text="No runs yet. Create one from an active plan." />}
    </Card>
  )
}

function RunDetail({ id, projectId, openDefect }: { id: string; projectId: string; openDefect: (id: string) => void }) {
  const q = useQuery<any>({ queryKey: ['test-run', id], queryFn: () => api.get(`/test-runs/${id}`) })
  const jobs = useQuery<any[]>({ queryKey: ['test-jobs', id], queryFn: () => api.get(`/test-runs/${id}/automation`) })
  const keys = [['test-run', id], ['test-runs', projectId], ['test-jobs', id], ['test-cases', projectId], ['defects', projectId], ['rtm', projectId]]
  const [exec, setExec] = useState<any>(null)
  const [closing, setClosing] = useState(false)
  const auto = useAction(() => api.post(`/test-runs/${id}/automation`, { tool: 'playwright' }), { success: 'Automated cases queued', invalidate: keys })
  if (!q.data) return <Loader type="dots" />
  const r = q.data
  return (
    <Stack>
      <div><Group gap={8}><Text size="xs" c="dimmed" fw={700}>{r.key}</Text><Badge size="sm" variant="light">{label(r.status)}</Badge><Text size="xs" c="dimmed">{r.plan.key} · build {r.build_version} · {r.environment}</Text></Group><Text fw={650} size="lg" mt={4}>{r.title}</Text></div>
      <SimpleGrid cols={4}>
        <Kpi label="Pass rate" value={`${r.exit.pass_rate}%`} icon={<IconCheck size={18} />} color="teal" />
        {['PASSED', 'FAILED', 'RETEST'].map((k) => <Kpi key={k} label={label(k)} value={r.exit.counts[k] || 0} icon={<IconListCheck size={18} />} color={RESULT_COLOR[k]} />)}
      </SimpleGrid>
      <Card withBorder>
        <Text size="sm" fw={600} mb={4}>Exit criteria</Text>
        <Stack gap={2}>{r.exit.checks.map((c: any) => <Group key={c.code} gap={6}>{c.ok ? <IconCheck size={14} color="teal" /> : <IconX size={14} color="red" />}<Text size="sm">{c.label}</Text><Text size="xs" c="dimmed">{c.detail}</Text></Group>)}
          {r.exit.manual.map((m: any) => <Group key={m.code} gap={6}><IconAlertTriangle size={14} /><Text size="sm">{m.label}</Text><Text size="xs" c="dimmed">confirmed at closure</Text></Group>)}</Stack>
        <Group mt="xs" gap="xs">
          {r.can_close && <Button size="xs" color="teal" leftSection={<IconLock size={14} />} onClick={() => setClosing(true)}>Close run</Button>}
          {r.can_execute && r.cases.some((c: any) => c.case.automation_id) && <Button size="xs" variant="light" leftSection={<IconRobot size={14} />} loading={auto.isPending} onClick={() => auto.mutate(undefined)}>Run automated cases</Button>}
          <TraceButton type="TEST_RUN" id={id} />
          {r.status === 'CLOSED' && <Text size="xs" c="dimmed">Closed by {r.closed_by?.full_name}: {r.closure_note}</Text>}
        </Group>
        {!!jobs.data?.length && <Stack gap={2} mt="xs">{jobs.data.map((j) => <Group key={j.id} gap={6}><Badge size="xs" color={j.status === 'FAILED' ? 'red' : j.status === 'SUCCEEDED' ? 'teal' : 'blue'}>{j.status.toLowerCase()}</Badge><Text size="xs">{j.tool} · {j.cases} case(s) · {j.results_received} result(s)</Text>{j.error && <Text size="xs" c="red">{j.error}</Text>}</Group>)}</Stack>}
      </Card>
      <Table verticalSpacing={6} fz="sm">
        <Table.Thead><Table.Tr><Table.Th>Case</Table.Th><Table.Th>Status</Table.Th><Table.Th>Last execution</Table.Th><Table.Th /></Table.Tr></Table.Thead>
        <Table.Tbody>
          {r.cases.map((rc: any) => {
            const last = rc.executions[rc.executions.length - 1]
            return (
              <Table.Tr key={rc.id}>
                <Table.Td><Text size="sm" fw={600}>{rc.case.key}</Text><Text size="xs" lineClamp={1}>{rc.case.title} · rev {rc.case.revision}</Text></Table.Td>
                <Table.Td><Tag v={rc.status} colors={RESULT_COLOR} /></Table.Td>
                <Table.Td>{last ? <Stack gap={0}><Group gap={4}><Text size="xs">{last.tester?.full_name || last.source.toLowerCase()}</Text><When at={last.executed_at} />{last.is_retest && <Badge size="xs" variant="outline">retest</Badge>}</Group>
                  {last.failure_cause && <Text size="xs" c="dimmed">cause: {label(last.failure_cause)}</Text>}
                  {last.defect && <Badge size="xs" color="red" variant="light" style={{ cursor: 'pointer' }} onClick={() => openDefect(last.defect.id)}>{last.defect.key} · {label(last.defect.status)}</Badge>}
                  {!!last.evidence.length && <Text size="xs" c="dimmed"><IconPaperclip size={11} /> {last.evidence.length} evidence file(s)</Text>}</Stack> : <Text size="xs" c="dimmed">—</Text>}</Table.Td>
                <Table.Td>{r.can_execute && <Button size="compact-xs" onClick={() => setExec(rc)}>{rc.status === 'RETEST' ? 'Retest' : 'Execute'}</Button>}</Table.Td>
              </Table.Tr>
            )
          })}
        </Table.Tbody>
      </Table>
      {exec && <ExecuteModal run={r} rc={exec} projectId={projectId} keys={keys} onClose={() => setExec(null)} />}
      {closing && <CloseModal run={r} keys={keys} onClose={() => setClosing(false)} />}
    </Stack>
  )
}

function ExecuteModal({ run, rc, projectId, keys, onClose }: { run: any; rc: any; projectId: string; keys: any[][]; onClose: () => void }) {
  const defects = useQuery<any>({ queryKey: ['defects', projectId, 'open'], queryFn: () => api.get(`/projects/${projectId}/defects`, { status: 'OPEN,IN_PROGRESS,FIXED,DEFERRED' }) })
  const [f, setF] = useState<any>({ result: 'PASSED', actual_result: '', failure_cause: null, defect_id: null, notes: '', new_title: '', severity: 'MEDIUM' })
  const [file, setFile] = useState<File | null>(null)
  const cause = run.failure_causes.find((c: any) => c.code === f.failure_cause)
  const needsDefect = f.result === 'FAILED' && cause?.creates_defect && rc.status !== 'RETEST'
  const save = useAction(async () => {
    const body: any = { result: f.result, actual_result: f.actual_result || null, failure_cause: f.result === 'FAILED' ? f.failure_cause : null, notes: f.notes || null }
    if (needsDefect) { if (f.defect_id) body.defect_id = f.defect_id; else if (f.new_title) body.new_defect = { title: f.new_title, severity: f.severity, description: f.actual_result || null } }
    const out: any = await api.post(`/test-runs/${run.id}/cases/${rc.id}/execute`, body)
    if (file) {
      const ex = out.cases.find((x: any) => x.id === rc.id).executions.slice(-1)[0]
      const fd = new FormData(); fd.append('file', file); fd.append('kind', file.type.startsWith('image/') ? 'SCREENSHOT' : 'ATTACHMENT')
      await api.post(`/test-executions/${ex.id}/evidence`, fd)
    }
    return out
  }, { success: 'Result recorded', invalidate: keys, onDone: onClose })
  return (
    <Modal opened onClose={onClose} size="lg" title={`${rc.status === 'RETEST' ? 'Retest' : 'Execute'} ${rc.case.key}`}>
      <Stack>
        <Table fz="xs"><Table.Tbody>{rc.case.steps.map((s: any, i: number) => <Table.Tr key={i}><Table.Td w={24}>{i + 1}</Table.Td><Table.Td>{s.action}</Table.Td><Table.Td c="dimmed">{s.expected}</Table.Td></Table.Tr>)}</Table.Tbody></Table>
        <Select label="Result" value={f.result} onChange={(v) => setF({ ...f, result: v })} allowDeselect={false} data={['PASSED', 'FAILED', 'BLOCKED', 'SKIPPED']} />
        <Textarea label="Actual result" autosize minRows={2} value={f.actual_result} onChange={(e) => setF({ ...f, actual_result: e.currentTarget.value })} />
        {f.result === 'FAILED' && <Select label="Failure cause" required value={f.failure_cause} onChange={(v) => setF({ ...f, failure_cause: v })} data={run.failure_causes.map((c: any) => ({ value: c.code, label: c.label + (c.creates_defect ? ' (creates or links a defect)' : '') }))} />}
        {needsDefect && (
          <Card withBorder>
            <Select label="Link an open defect" clearable searchable value={f.defect_id} onChange={(v) => setF({ ...f, defect_id: v })} data={(defects.data?.items || []).map((d: any) => ({ value: d.id, label: `${d.key} ${d.title}` }))} />
            {!f.defect_id && <Group grow mt="xs"><TextInput label="…or raise a new defect" placeholder={`${rc.case.key} fails: …`} value={f.new_title} onChange={(e) => setF({ ...f, new_title: e.currentTarget.value })} /><Select label="Severity" w={140} value={f.severity} onChange={(v) => setF({ ...f, severity: v })} data={Object.keys(SEV_COLOR)} allowDeselect={false} /></Group>}
          </Card>
        )}
        {f.result === 'FAILED' && cause && !cause.creates_defect && <Text size="xs" c="dimmed">Recorded as an analysis outcome; no defect is raised.</Text>}
        <Textarea label="Notes" autosize minRows={1} value={f.notes} onChange={(e) => setF({ ...f, notes: e.currentTarget.value })} />
        <Group gap="xs"><FileButton onChange={setFile}>{(props) => <Button size="xs" variant="default" leftSection={<IconPaperclip size={14} />} {...props}>Evidence</Button>}</FileButton>{file && <Text size="xs">{file.name}</Text>}</Group>
        <Group justify="flex-end"><Button variant="default" onClick={onClose}>Cancel</Button><Button disabled={f.result === 'FAILED' && !f.failure_cause} loading={save.isPending} onClick={() => save.mutate(undefined)}>Record result</Button></Group>
      </Stack>
    </Modal>
  )
}

function CloseModal({ run, keys, onClose }: { run: any; keys: any[][]; onClose: () => void }) {
  const [note, setNote] = useState('')
  const [checks, setChecks] = useState<boolean[]>(run.exit.manual.map(() => false))
  const close = useAction(() => api.post(`/test-runs/${run.id}/close`, { note, manual_confirmed: checks }), { success: 'Run closed', invalidate: keys, onDone: onClose })
  return (
    <Modal opened onClose={onClose} title={`Close ${run.key}`}>
      <Stack>
        {!run.exit.automatic_ok && <Alert color="orange" icon={<IconAlertTriangle size={16} />}>Some exit criteria are not met; closing will be refused until they are.</Alert>}
        {run.exit.manual.map((m: any, i: number) => <Checkbox key={m.code} label={m.label} checked={checks[i]} onChange={(e) => setChecks(checks.map((c, j) => (j === i ? e.currentTarget.checked : c)))} />)}
        <Textarea label="Closure note" required autosize minRows={2} value={note} onChange={(e) => setNote(e.currentTarget.value)} />
        <Text size="xs" c="dimmed">The executor of the run cannot close it.</Text>
        <Group justify="flex-end"><Button variant="default" onClick={onClose}>Cancel</Button><Button disabled={note.trim().length < 3} loading={close.isPending} onClick={() => close.mutate(undefined)}>Close run</Button></Group>
      </Stack>
    </Modal>
  )
}

// ------------------------------------------------------------------ defects
function Defects({ projectId, open }: { projectId: string; open: (id: string) => void }) {
  const [status, setStatus] = useState<string | null>('OPEN,IN_PROGRESS,FIXED,VERIFIED,DEFERRED')
  const list = useQuery<any>({ queryKey: ['defects', projectId, status], queryFn: () => api.get(`/projects/${projectId}/defects`, { status }) })
  const [raising, setRaising] = useState(false)
  const [f, setF] = useState<any>({ title: '', severity: 'MEDIUM', description: '' })
  const raise = useAction(() => api.post(`/projects/${projectId}/defects`, f), { success: (d: any) => `${d.key} raised`, invalidate: [['defects', projectId]], onDone: (d: any) => { setRaising(false); open(d.id) } })
  const states = list.data?.states || []
  return (
    <Stack>
      <Group justify="space-between">
        <Select size="xs" w={240} value={status} onChange={setStatus} clearable placeholder="All statuses" data={[{ value: 'OPEN,IN_PROGRESS,FIXED,VERIFIED,DEFERRED', label: 'Not closed' }, ...states.map((s: any) => ({ value: s.code, label: s.label }))]} />
        {list.data?.can_raise && <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => setRaising(true)}>Raise defect</Button>}
      </Group>
      <Card withBorder p={0}>
        <Table highlightOnHover verticalSpacing={6}>
          <Table.Thead><Table.Tr><Table.Th>Defect</Table.Th><Table.Th>Severity</Table.Th><Table.Th>Status</Table.Th><Table.Th>Found in</Table.Th><Table.Th>Fixed in</Table.Th><Table.Th>Assignee</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>{(list.data?.items || []).map((d: any) => <Table.Tr key={d.id} style={{ cursor: 'pointer' }} onClick={() => open(d.id)}><Table.Td><Group gap={8}><Text size="xs" fw={700} c="dimmed">{d.key}</Text><Text size="sm" lineClamp={1}>{d.title}</Text></Group></Table.Td><Table.Td><Badge size="xs" color={SEV_COLOR[d.severity]}>{d.severity}</Badge></Table.Td><Table.Td><Badge size="sm" variant="light" color={states.find((s: any) => s.code === d.status)?.color}>{label(d.status)}</Badge></Table.Td><Table.Td><Text size="xs">{d.found_in_build || '—'}</Text></Table.Td><Table.Td><Text size="xs">{d.fixed_in_build || '—'}</Text></Table.Td><Table.Td>{d.assignee && <UserAvatar user={d.assignee} size={22} />}</Table.Td></Table.Tr>)}</Table.Tbody>
        </Table>
        {!list.data?.items?.length && <EmptyBlock text="No defects." />}
      </Card>
      <Modal opened={raising} onClose={() => setRaising(false)} title="Raise a defect">
        <Stack>
          <TextInput label="Title" required value={f.title} onChange={(e) => setF({ ...f, title: e.currentTarget.value })} />
          <Select label="Severity" value={f.severity} onChange={(v) => setF({ ...f, severity: v })} data={Object.keys(SEV_COLOR)} allowDeselect={false} />
          <Textarea label="Description" autosize minRows={3} value={f.description} onChange={(e) => setF({ ...f, description: e.currentTarget.value })} />
          <Group justify="flex-end"><Button variant="default" onClick={() => setRaising(false)}>Cancel</Button><Button disabled={f.title.length < 3} loading={raise.isPending} onClick={() => raise.mutate(undefined)}>Raise</Button></Group>
        </Stack>
      </Modal>
    </Stack>
  )
}

function DefectDetail({ id, projectId }: { id: string; projectId: string }) {
  const q = useQuery<any>({ queryKey: ['defect', id], queryFn: () => api.get(`/defects/${id}`) })
  const users = useUsers()
  const keys = [['defect', id], ['defects', projectId], ['rtm', projectId]]
  const [move, setMove] = useState<any>(null)
  const [comment, setComment] = useState('')
  const [build, setBuild] = useState('')
  const go = useAction((v: any) => api.post(`/defects/${id}/transition`, v, { version: q.data.version }), { success: 'Defect updated', invalidate: keys, onDone: () => { setMove(null); setComment(''); setBuild('') } })
  const assign = useAction((assignee: string | null) => api.put(`/defects/${id}`, { title: q.data.title, description: q.data.description, severity: q.data.severity, priority: q.data.priority, assignee_id: assignee, found_in_build: q.data.found_in_build, work_item_id: q.data.task?.id || null }, { version: q.data.version }), { success: 'Assigned', invalidate: keys })
  if (!q.data) return <Loader type="dots" />
  const d = q.data
  return (
    <Stack>
      <div><Group gap={8}><Text size="xs" c="dimmed" fw={700}>{d.key}</Text><Badge size="xs" color={SEV_COLOR[d.severity]}>{d.severity}</Badge><Badge size="sm" variant="light">{label(d.status)}</Badge></Group><Text fw={650} size="lg" mt={4}>{d.title}</Text>{d.description && <Text size="sm" c="dimmed">{d.description}</Text>}</div>
      <Group gap="xs"><TraceButton type="DEFECT" id={id} />{d.transitions.map((t: any) => <Button key={t.to} size="xs" variant="light" onClick={() => (t.reason_required || t.to === 'FIXED' ? setMove(t) : go.mutate({ to: t.to }))}>{t.label}</Button>)}{!d.transitions.length && <Text size="xs" c="dimmed">No status change is available to you.</Text>}</Group>
      {move && (
        <Card withBorder>
          <Stack gap="xs">
            {move.to === 'FIXED' && <TextInput size="xs" label="Fixed in build" value={build} onChange={(e) => setBuild(e.currentTarget.value)} />}
            <Textarea size="xs" label={move.reason_required ? 'Reason' : 'Comment'} required={move.reason_required} autosize minRows={2} value={comment} onChange={(e) => setComment(e.currentTarget.value)} />
            <Group gap="xs"><Button size="xs" disabled={move.reason_required && !comment.trim()} loading={go.isPending} onClick={() => go.mutate({ to: move.to, comment: comment || undefined, fixed_in_build: build || undefined })}>{move.label}</Button><Button size="xs" variant="subtle" onClick={() => setMove(null)}>Cancel</Button></Group>
          </Stack>
        </Card>
      )}
      <Group grow>
        <Select label="Assignee" disabled={!d.can_edit} clearable searchable value={d.assignee?.id || null} onChange={(v) => assign.mutate(v)} data={(users.data || []).map((u) => ({ value: u.id, label: u.full_name }))} />
        <TextInput label="Found / fixed in" disabled value={`${d.found_in_build || '—'} / ${d.fixed_in_build || '—'}`} />
      </Group>
      {d.fixed_by && <Text size="xs" c="dimmed">Fixed by {d.fixed_by.full_name}; someone else verifies it (a passing retest verifies it automatically).</Text>}
      <Tabs defaultValue="executions" keepMounted={false}>
        <Tabs.List><Tabs.Tab value="executions">Executions ({d.executions.length})</Tabs.Tab><Tabs.Tab value="links">Traceability ({d.links.length})</Tabs.Tab><Tabs.Tab value="history">History</Tabs.Tab></Tabs.List>
        <Tabs.Panel value="executions" pt="md"><Stack gap={4}>{d.executions.map((e: any) => <Group key={e.id} gap="xs"><Tag v={e.result} colors={RESULT_COLOR} /><Text size="sm">{e.run.key} · {e.case.key}</Text>{e.is_retest && <Badge size="xs" variant="outline">retest</Badge>}<When at={e.at} /></Group>)}</Stack></Tabs.Panel>
        <Tabs.Panel value="links" pt="md"><LinksPanel links={d.links} projectId={projectId} addUrl={`/defects/${id}/links`} keys={keys} canEdit={d.can_edit} types={['REQUIREMENT', 'TASK', 'DESIGN']} linkTypes={['affects', 'related_to']} /></Tabs.Panel>
        <Tabs.Panel value="history" pt="md"><HistoryPanel history={d.history} /></Tabs.Panel>
      </Tabs>
    </Stack>
  )
}

// ------------------------------------------------------------------ coverage
function Coverage({ projectId }: { projectId: string }) {
  const q = useQuery<any>({ queryKey: ['test-summary', projectId], queryFn: () => api.get(`/projects/${projectId}/test-summary`) })
  const s = q.data
  if (!s) return null
  const pct = (n: number) => (s.requirements ? `${Math.round((100 * n) / s.requirements)}% of ${s.requirements}` : undefined)
  return (
    <Stack>
      <SimpleGrid cols={{ base: 2, md: 4 }}>
        <Kpi label="Requirements with approved test cases" value={s.covered_by_approved_cases} icon={<IconListCheck size={20} />} color="cyan" hint={pct(s.covered_by_approved_cases)} />
        <Kpi label="All linked tests passing" value={s.all_linked_cases_passing} icon={<IconCheck size={20} />} color="teal" hint={pct(s.all_linked_cases_passing)} />
        <Kpi label="Test cases" value={s.cases} icon={<IconFlask size={20} />} color="blue" />
        <Kpi label="Open defects" value={(s.defects_by_status.OPEN || 0) + (s.defects_by_status.IN_PROGRESS || 0) + (s.defects_by_status.FIXED || 0)} icon={<IconBug size={20} />} color="red" />
      </SimpleGrid>
      <Text size="sm" c="dimmed">Per-requirement detail is in the traceability matrix on the Requirements page.</Text>
    </Stack>
  )
}
