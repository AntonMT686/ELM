import { Alert, Anchor, Badge, Button, Card, Checkbox, Code, Drawer, Group, Loader, Modal, MultiSelect, NumberInput, ScrollArea, Select, SimpleGrid, Stack, Switch, Table, Tabs, TagsInput, Text, Textarea, TextInput, Tooltip } from '@mantine/core'
import { IconAlertTriangle, IconArrowBackUp, IconCheck, IconCloudUpload, IconLock, IconPlayerPlay, IconPlus, IconRocket, IconSend, IconServer, IconSettings, IconX } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { useAction, useProjects, useUsers } from '../api/hooks'
import { HistoryPanel, ReasonModal, ReviewPanel } from '../components/ArtifactParts'
import { EmptyBlock, Hash, PageTitle, UserAvatar, When } from '../components/common'

const ATTEMPT_COLOR: Record<string, string> = { QUEUED: 'gray', RUNNING: 'blue', WAITING: 'violet', SUCCEEDED: 'teal', FAILED: 'red' }
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function Status({ status, states }: { status: string; states?: any[] }) {
  const s = states?.find((x) => x.code === status)
  return <Badge size="sm" variant="light" radius="xl" color={s?.color || 'gray'} style={{ textTransform: 'none' }}>{s?.label || status.replace(/_/g, ' ').toLowerCase()}</Badge>
}

export default function DeploymentsPage() {
  const { projectId } = useParams()
  const nav = useNavigate()
  const projects = useProjects()
  useEffect(() => { if (!projectId && projects.data?.length === 1) nav(`/deployments/${projects.data[0].id}`, { replace: true }) }, [projectId, projects.data, nav])
  return (
    <div className="page" style={{ maxWidth: 1700 }}>
      <PageTitle icon={<IconRocket size={22} />} title="Deployments" sub="Software releases to environments: approvals, validation gates, execution with logs and health checks, retry and rollback. (Controlled documents are released in the Release register.)"
        extra={<Select w={260} placeholder="Choose a project" searchable value={projectId || null} onChange={(v) => v && nav(`/deployments/${v}`)} allowDeselect={false} data={(projects.data || []).map((p) => ({ value: p.id, label: `${p.code} — ${p.name}` }))} />} />
      {projectId ? <Project key={projectId} projectId={projectId} /> : <EmptyBlock text="Choose a project." />}
    </div>
  )
}

function Project({ projectId }: { projectId: string }) {
  const [sp, setSp] = useSearchParams()
  const open = sp.get('open')
  const setOpen = (id: string | null) => { if (id) sp.set('open', id); else sp.delete('open'); setSp(sp, { replace: true }) }
  const list = useQuery<any>({ queryKey: ['deployments', projectId], queryFn: () => api.get(`/projects/${projectId}/deployments`), refetchInterval: 15_000 })
  const envs = useQuery<any>({ queryKey: ['deploy-envs', projectId], queryFn: () => api.get(`/projects/${projectId}/deploy-environments`) })
  const overview = useQuery<any[]>({ queryKey: ['deploy-overview', projectId], queryFn: () => api.get(`/projects/${projectId}/deployment-overview`), refetchInterval: 15_000 })
  const [creating, setCreating] = useState(false)
  if (list.isError) return <Alert color="red" icon={<IconLock size={16} />}>You do not have access to this project.</Alert>
  const states = list.data?.states || []
  return (
    <>
      <Tabs defaultValue="overview" keepMounted={false}>
        <Tabs.List mb="md">
          <Tabs.Tab value="overview" leftSection={<IconServer size={15} />}>What runs where</Tabs.Tab>
          <Tabs.Tab value="list" leftSection={<IconCloudUpload size={15} />}>Deployments ({list.data?.items.length ?? '…'})</Tabs.Tab>
          <Tabs.Tab value="envs" leftSection={<IconSettings size={15} />}>Environments</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="overview">
          <SimpleGrid cols={{ base: 1, md: 3 }}>
            {(overview.data || []).map((o) => (
              <Card key={o.environment.id} withBorder>
                <Group justify="space-between"><Text fw={650}>{o.environment.code}</Text><Text size="xs" c="dimmed">{o.environment.name}</Text></Group>
                {o.current ? <Stack gap={0} mt="xs"><Text size="xl" fw={700}>{o.current.version_label}</Text><Text size="xs" c="dimmed">{o.current.key} · deployed <When at={o.current.deployed_at} /></Text></Stack> : <Text size="sm" c="dimmed" mt="xs">Nothing deployed yet</Text>}
                <Stack gap={4} mt="sm">{o.in_flight.map((d: any) => <Group key={d.id} gap={6} style={{ cursor: 'pointer' }} onClick={() => setOpen(d.id)}><Status status={d.status} states={states} /><Text size="sm">{d.version_label}</Text><Text size="xs" c="dimmed">{d.key}</Text></Group>)}</Stack>
              </Card>
            ))}
          </SimpleGrid>
          {!overview.data?.length && <EmptyBlock text="No environments yet. A project engineer can add them under Environments." />}
        </Tabs.Panel>
        <Tabs.Panel value="list">
          <Group justify="flex-end" mb="sm">{list.data?.can_request && <Button size="xs" leftSection={<IconPlus size={14} />} disabled={!envs.data?.items.length} onClick={() => setCreating(true)}>Request deployment</Button>}</Group>
          <Card withBorder p={0}>
            <Table highlightOnHover verticalSpacing={6}>
              <Table.Thead><Table.Tr><Table.Th>Deployment</Table.Th><Table.Th>Environment</Table.Th><Table.Th>Version</Table.Th><Table.Th>Status</Table.Th><Table.Th>Requested by</Table.Th><Table.Th>Created</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>
                {(list.data?.items || []).map((d: any) => (
                  <Table.Tr key={d.id} style={{ cursor: 'pointer' }} onClick={() => setOpen(d.id)}>
                    <Table.Td><Group gap={8}><Text size="xs" fw={700} c="dimmed">{d.key}</Text><Text size="sm" lineClamp={1}>{d.title}</Text>{d.rollback_of_id && <Badge size="xs" color="orange" variant="outline">rollback</Badge>}</Group></Table.Td>
                    <Table.Td><Badge size="sm" variant="outline">{d.environment?.code}</Badge></Table.Td>
                    <Table.Td><Text size="sm" fw={600}>{d.version_label}</Text>{d.git_ref && <Text size="xs" c="dimmed">{d.git_ref}</Text>}</Table.Td>
                    <Table.Td><Status status={d.status} states={states} /></Table.Td>
                    <Table.Td>{d.requested_by && <UserAvatar user={d.requested_by} size={22} />}</Table.Td>
                    <Table.Td><When at={d.created_at} /></Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
            {!list.data?.items.length && <EmptyBlock text="No deployments yet." />}
          </Card>
        </Tabs.Panel>
        <Tabs.Panel value="envs"><Environments projectId={projectId} data={envs.data} /></Tabs.Panel>
      </Tabs>
      {creating && <CreateModal projectId={projectId} envs={envs.data?.items || []} onClose={() => setCreating(false)} onSaved={(d) => { setCreating(false); setOpen(d.id) }} />}
      <Drawer opened={!!open} onClose={() => setOpen(null)} position="right" size={820} title={<Text fw={650}>Deployment</Text>}>
        {open && <Detail key={open} id={open} projectId={projectId} states={states} onOpen={setOpen} />}
      </Drawer>
    </>
  )
}

function CreateModal({ projectId, envs, onClose, onSaved }: { projectId: string; envs: any[]; onClose: () => void; onSaved: (d: any) => void }) {
  const repos = useQuery<any>({ queryKey: ['repositories', projectId], queryFn: () => api.get(`/projects/${projectId}/repositories`) })
  const runs = useQuery<any[]>({ queryKey: ['test-runs', projectId], queryFn: () => api.get(`/projects/${projectId}/test-runs`) })
  const tasks = useQuery<any[]>({ queryKey: ['work-items', 'scope', projectId], queryFn: () => api.get('/work-items', { project_id: projectId }) })
  const [f, setF] = useState<any>({ environment_id: envs[0]?.id, version_label: '', repository_id: null, git_ref: '', commit_sha: '', test_run_id: null, task_ids: [], release_notes: '' })
  const body = { ...f, git_ref: f.git_ref || null, commit_sha: f.commit_sha || null, release_notes: f.release_notes || null }
  const save = useAction(() => api.post(`/projects/${projectId}/deployments`, body), { success: (d: any) => `${d.key} requested`, invalidate: [['deployments', projectId], ['deploy-overview', projectId]], onDone: onSaved })
  return (
    <Modal opened onClose={onClose} size="lg" title="Request a deployment">
      <Stack>
        <Group grow>
          <Select label="Environment" required allowDeselect={false} value={f.environment_id} onChange={(v) => setF({ ...f, environment_id: v })} data={envs.filter((e) => e.active).map((e) => ({ value: e.id, label: `${e.code} — ${e.name}` }))} />
          <TextInput label="Version" required placeholder="e.g. 1.5.0" value={f.version_label} onChange={(e) => setF({ ...f, version_label: e.currentTarget.value })} />
        </Group>
        <Group grow>
          <Select label="Repository" clearable value={f.repository_id} onChange={(v) => setF({ ...f, repository_id: v })} data={(repos.data?.items || []).map((r: any) => ({ value: r.id, label: r.path }))} />
          <TextInput label="Tag or branch" placeholder="v1.5.0" value={f.git_ref} onChange={(e) => setF({ ...f, git_ref: e.currentTarget.value })} />
        </Group>
        <TextInput label="Commit SHA" placeholder="the exact commit being released" value={f.commit_sha} onChange={(e) => setF({ ...f, commit_sha: e.currentTarget.value.trim() })} />
        <Select label="Test run (evidence)" clearable value={f.test_run_id} onChange={(v) => setF({ ...f, test_run_id: v })} data={(runs.data || []).map((r) => ({ value: r.id, label: `${r.key} ${r.title} · ${r.status.toLowerCase()} · build ${r.build_version || '—'}` }))} />
        <MultiSelect label="Tasks included" searchable value={f.task_ids} onChange={(v) => setF({ ...f, task_ids: v })} data={(tasks.data || []).map((t) => ({ value: t.id, label: `${t.key} ${t.title}` }))} description="Release notes are drafted from these tasks and their merge requests if you leave the notes empty." />
        <Textarea label="Release notes" autosize minRows={3} value={f.release_notes} onChange={(e) => setF({ ...f, release_notes: e.currentTarget.value })} />
        <Group justify="flex-end"><Button variant="default" onClick={onClose}>Cancel</Button><Button disabled={!f.version_label || !f.environment_id} loading={save.isPending} onClick={() => save.mutate(undefined)}>Request</Button></Group>
      </Stack>
    </Modal>
  )
}

function Detail({ id, projectId, states, onOpen }: { id: string; projectId: string; states: any[]; onOpen: (id: string) => void }) {
  const q = useQuery<any>({ queryKey: ['deployment', id], queryFn: () => api.get(`/deployments/${id}`), refetchInterval: (qq) => (['DEPLOYING'].includes((qq.state.data as any)?.status) ? 5000 : false) })
  const users = useUsers()
  const keys = [['deployment', id], ['deployments', projectId], ['deploy-overview', projectId]]
  const [approvers, setApprovers] = useState<string[]>([])
  const [ask, setAsk] = useState<null | 'cancel' | 'rollback'>(null)
  const [report, setReport] = useState<any>(null)
  const submit = useAction(() => api.post(`/deployments/${id}/submit`, { approvers }), { success: 'Submitted', invalidate: keys })
  const execute = useAction(() => api.post(`/deployments/${id}/execute`), { success: (r: any) => `Attempt ${r.attempt_no} queued (job ${r.job_id.slice(0, 8)})`, invalidate: keys })
  const tick = useAction((v: { item: string; done: boolean }) => api.post(`/deployments/${id}/checklist`, v), { invalidate: keys })
  const cancel = useAction((reason: string) => api.post(`/deployments/${id}/cancel`, { reason }), { success: 'Cancelled', invalidate: keys, onDone: () => setAsk(null) })
  const rollback = useAction((reason: string) => api.post(`/deployments/${id}/rollback`, { reason }), { success: (r: any) => `${r.key} created to roll back`, invalidate: keys, onDone: (r: any) => { setAsk(null); onOpen(r.id) } })
  const doReport = useAction(() => api.post(`/deployment-attempts/${report.attempt}/report`, { outcome: report.outcome, log: report.log || null, reason: report.reason || null }), { success: 'Result recorded', invalidate: keys, onDone: () => setReport(null) })
  if (!q.data) return <Loader type="dots" />
  const d = q.data
  const cfg = d.environment_config
  const waiting = d.attempts.find((a: any) => a.status === 'WAITING' && a.adapter === 'manual')
  return (
    <Stack>
      <div>
        <Group gap={8}><Text size="xs" c="dimmed" fw={700}>{d.key}</Text><Status status={d.status} states={states} /><Badge size="sm" variant="outline">{d.environment.code}</Badge>{d.rollback_of && <Badge size="xs" color="orange">rollback of {d.rollback_of.key}</Badge>}<Hash value={d.sha256} /></Group>
        <Text fw={650} size="lg" mt={4}>{d.title}</Text>
        <Text size="sm" c="dimmed">Version <b>{d.version_label}</b>{d.git_ref ? ` · ${d.git_ref}` : ''}{d.commit_sha ? ` · ${d.commit_sha.slice(0, 12)}` : ''}{d.repository ? ` · ${d.repository.path}` : ''} · adapter {cfg.adapter.replace('_', ' ')}{cfg.health_check ? ' + health check' : ''}</Text>
        {d.status_reason && <Text size="xs" c="dimmed">{d.status_reason}</Text>}
      </div>
      <Group gap="xs">
        {d.status === 'PLANNED' && d.can_edit && (cfg.requires_approval
          ? <Group gap={6} align="flex-end"><MultiSelect size="xs" w={320} placeholder={`${cfg.approvals_required} approver(s)`} searchable value={approvers} onChange={setApprovers} data={(users.data || []).map((u) => ({ value: u.id, label: u.full_name }))} /><Button size="xs" leftSection={<IconSend size={14} />} disabled={approvers.length < cfg.approvals_required} loading={submit.isPending} onClick={() => submit.mutate(undefined)}>Submit for approval</Button></Group>
          : <Button size="xs" leftSection={<IconSend size={14} />} loading={submit.isPending} onClick={() => submit.mutate(undefined)}>Submit (no approval needed)</Button>)}
        {d.can_execute && ['APPROVED', 'FAILED'].includes(d.status) && <Button size="xs" color={d.status === 'FAILED' ? 'orange' : 'blue'} leftSection={<IconPlayerPlay size={14} />} loading={execute.isPending} onClick={() => execute.mutate(undefined)}>{d.status === 'FAILED' ? 'Retry' : 'Deploy'}</Button>}
        {d.can_report && waiting && <Button size="xs" color="teal" variant="light" onClick={() => setReport({ attempt: waiting.id, outcome: 'SUCCEEDED', log: '', reason: '' })}>Record result</Button>}
        {d.can_rollback && <Button size="xs" color="orange" variant="light" leftSection={<IconArrowBackUp size={14} />} onClick={() => setAsk('rollback')}>Roll back</Button>}
        {['PLANNED', 'AWAITING_APPROVAL', 'APPROVED'].includes(d.status) && <Button size="xs" variant="subtle" color="gray" onClick={() => setAsk('cancel')}>Cancel</Button>}
      </Group>
      {d.gates && (
        <Card withBorder>
          <Text size="sm" fw={600} mb={4}>Validation gates</Text>
          <Stack gap={3}>{d.gates.map((g: any) => <Group key={g.code} gap={6} wrap="nowrap" align="flex-start">{g.ok ? <IconCheck size={15} color="teal" /> : <IconX size={15} color="red" />}<Text size="sm">{g.label}</Text><Text size="xs" c={g.ok ? 'dimmed' : 'red'}>{g.detail}</Text></Group>)}</Stack>
        </Card>
      )}
      {!!d.checklist.length && (
        <Card withBorder>
          <Text size="sm" fw={600} mb={4}>Release checklist</Text>
          <Stack gap={4}>{d.checklist.map((c: any) => <Checkbox key={c.text} label={c.text} checked={c.done} disabled={!['PLANNED', 'AWAITING_APPROVAL', 'APPROVED', 'FAILED'].includes(d.status)} onChange={(e) => tick.mutate({ item: c.text, done: e.currentTarget.checked })} />)}</Stack>
        </Card>
      )}
      <Tabs defaultValue={d.attempts.length ? 'attempts' : 'notes'} keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="notes">Release notes</Tabs.Tab>
          <Tabs.Tab value="approvals">Approval ({d.approvals.length})</Tabs.Tab>
          <Tabs.Tab value="attempts">Execution ({d.attempts.length})</Tabs.Tab>
          <Tabs.Tab value="links">Included ({d.links.length})</Tabs.Tab>
          <Tabs.Tab value="history">History</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="notes" pt="md">
          <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>{d.release_notes || 'No release notes.'}</Text>
          {d.test_run && <Text size="xs" c="dimmed" mt="xs">Test evidence: {d.test_run.key} {d.test_run.title} ({d.test_run.status.toLowerCase().replace('_', ' ')}, build {d.test_run.build_version || '—'})</Text>}
        </Tabs.Panel>
        <Tabs.Panel value="approvals" pt="md"><ReviewPanel reviews={d.approvals} decideUrl={(rid) => `/deployments/${id}/approvals/${rid}/decide`} keys={keys} /></Tabs.Panel>
        <Tabs.Panel value="attempts" pt="md">
          <Stack>
            {d.attempts.map((a: any) => (
              <Card key={a.id} withBorder>
                <Group justify="space-between">
                  <Group gap={6}><Text fw={600}>Attempt {a.attempt_no}</Text><Badge size="sm" color={ATTEMPT_COLOR[a.status]}>{a.status.toLowerCase()}</Badge><Text size="xs" c="dimmed">{a.adapter.replace('_', ' ')} · {a.target}{a.worker ? ` · worker ${a.worker}` : ''}</Text></Group>
                  <Group gap={6}>{a.external_url && <Anchor size="xs" href={a.external_url} target="_blank">pipeline {a.external_ref}</Anchor>}<When at={a.finished_at || a.started_at || a.queued_at} /></Group>
                </Group>
                {a.failure_reason && <Alert mt="xs" p="xs" color="red" icon={<IconAlertTriangle size={14} />}>{a.failure_reason}</Alert>}
                {a.health && !a.health.skipped && <Text size="xs" mt={4} c={a.health.ok ? 'teal' : 'red'}>Health check {a.health.ok ? 'passed' : 'failed'} · {a.health.url} · {a.health.tries?.length} try(ies)</Text>}
                {a.log && <ScrollArea.Autosize mah={220} mt="xs"><Code block fz={11}>{a.log}</Code></ScrollArea.Autosize>}
              </Card>
            ))}
            {!d.attempts.length && <Text size="sm" c="dimmed">Not executed yet.</Text>}
          </Stack>
        </Tabs.Panel>
        <Tabs.Panel value="links" pt="md"><Stack gap={4}>{d.links.map((l: any) => <Group key={l.id} gap={6}><Badge size="xs" variant="light">{l.target.type.toLowerCase()}</Badge><Text size="sm" fw={600}>{l.target.key}</Text><Text size="sm">{l.target.title}</Text><Badge size="xs" color="gray">{String(l.target.status).toLowerCase()}</Badge></Group>)}{!d.links.length && <Text size="sm" c="dimmed">No tasks or documents linked.</Text>}</Stack></Tabs.Panel>
        <Tabs.Panel value="history" pt="md"><HistoryPanel history={d.history} /></Tabs.Panel>
      </Tabs>
      <ReasonModal opened={ask === 'cancel'} title="Cancel this deployment" onClose={() => setAsk(null)} loading={cancel.isPending} onConfirm={(r) => cancel.mutate(r)} />
      <ReasonModal opened={ask === 'rollback'} title="Roll back to the previous version" label="Reason (a new deployment is created; it needs the same approvals and gates)" onClose={() => setAsk(null)} loading={rollback.isPending} onConfirm={(r) => rollback.mutate(r)} />
      <Modal opened={!!report} onClose={() => setReport(null)} title="Record the deployment result">
        {report && <Stack>
          <Select label="Outcome" value={report.outcome} onChange={(v) => setReport({ ...report, outcome: v })} allowDeselect={false} data={[{ value: 'SUCCEEDED', label: 'Succeeded (the health check still runs)' }, { value: 'FAILED', label: 'Failed' }]} />
          {report.outcome === 'FAILED' && <TextInput label="Reason" required value={report.reason} onChange={(e) => setReport({ ...report, reason: e.currentTarget.value })} />}
          <Textarea label="Log / notes" autosize minRows={4} value={report.log} onChange={(e) => setReport({ ...report, log: e.currentTarget.value })} description="Passwords and tokens are masked before the log is stored." />
          <Group justify="flex-end"><Button variant="default" onClick={() => setReport(null)}>Cancel</Button><Button disabled={report.outcome === 'FAILED' && !report.reason.trim()} loading={doReport.isPending} onClick={() => doReport.mutate(undefined)}>Record</Button></Group>
        </Stack>}
      </Modal>
    </Stack>
  )
}

// ------------------------------------------------------------------ environments
function Environments({ projectId, data }: { projectId: string; data: any }) {
  const [edit, setEdit] = useState<any>(null)
  const keys = [['deploy-envs', projectId], ['deploy-overview', projectId]]
  const approve = useAction((eid: string) => api.post(`/deploy-environments/${eid}/approve-config`), { success: 'Configuration approved', invalidate: keys })
  if (!data) return null
  return (
    <Stack>
      {data.can_configure && <Group justify="flex-end"><Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => setEdit({ code: '', name: '', description: '', sort_order: data.items.length, active: true, config: { ...data.default_config } })}>New environment</Button></Group>}
      {data.items.map((e: any) => {
        const c = e.config
        return (
          <Card key={e.id} withBorder>
            <Group justify="space-between">
              <Group gap={8}><Text fw={650}>{e.code}</Text><Text size="sm">{e.name}</Text>{!e.active && <Badge color="gray">off</Badge>}
                {c.require_config_approval ? <Tooltip label={e.config_approved_by ? `Approved by ${e.config_approved_by.full_name}` : 'Changed since last approval'}><Badge color={e.config_status === 'APPROVED' ? 'teal' : 'orange'} variant="light">config {e.config_status.toLowerCase()}</Badge></Tooltip> : <Badge color="gray" variant="light">config approval not required</Badge>}<Hash value={e.config_sha256} /></Group>
              <Group gap="xs">
                {data.can_approve && c.require_config_approval && e.config_status !== 'APPROVED' && <Button size="xs" color="teal" variant="light" onClick={() => approve.mutate(e.id)}>Approve configuration</Button>}
                {data.can_configure && <Button size="xs" variant="default" onClick={() => setEdit(e)}>Edit</Button>}
              </Group>
            </Group>
            <Group gap={6} mt="xs">
              <Badge size="xs" variant="outline">{c.requires_approval ? `${c.approvals_required} approval(s)` : 'no approval'}</Badge>
              {c.require_test_run && <Badge size="xs" variant="outline">closed test run{c.match_test_build ? ' of this build' : ''}</Badge>}
              {!!c.blocking_defect_severities.length && <Badge size="xs" variant="outline">no open {c.blocking_defect_severities.join('/').toLowerCase()} defects</Badge>}
              {!!c.required_document_types.length && <Badge size="xs" variant="outline">released {c.required_document_types.join(', ')}</Badge>}
              {!!c.checklist.length && <Badge size="xs" variant="outline">{c.checklist.length} checklist item(s)</Badge>}
              {c.change_window && <Badge size="xs" variant="outline">{c.change_window.days.map((i: number) => DAYS[i]).join(' ')} {c.change_window.start}–{c.change_window.end}</Badge>}
              {c.require_commit && <Badge size="xs" variant="outline">verified commit</Badge>}
              <Badge size="xs" color="indigo" variant="light">{c.adapter.replace('_', ' ')}</Badge>
              {c.health_check && <Badge size="xs" color="cyan" variant="light">health check</Badge>}
            </Group>
          </Card>
        )
      })}
      {!data.items.length && <EmptyBlock text="No environments configured." />}
      {edit && <EnvModal projectId={projectId} value={edit} keys={keys} onClose={() => setEdit(null)} />}
    </Stack>
  )
}

function EnvModal({ projectId, value, keys, onClose }: { projectId: string; value: any; keys: any[][]; onClose: () => void }) {
  const repos = useQuery<any>({ queryKey: ['repositories', projectId], queryFn: () => api.get(`/projects/${projectId}/repositories`) })
  const [f, setF] = useState<any>(() => JSON.parse(JSON.stringify({ code: value.code, name: value.name, description: value.description || '', sort_order: value.sort_order, active: value.active, config: value.config })))
  const c = f.config
  const setC = (k: string, v: any) => setF({ ...f, config: { ...c, [k]: v } })
  const save = useAction(() => (value.id ? api.put(`/deploy-environments/${value.id}`, f, { version: value.version }) : api.post(`/projects/${projectId}/deploy-environments`, f)), { success: 'Environment saved (configuration needs approval)', invalidate: keys, onDone: onClose })
  const hc = c.health_check || { url: '', expect_status: 200, retries: 3, timeout_seconds: 10 }
  return (
    <Modal opened onClose={onClose} size="xl" title={value.id ? `Edit ${value.code}` : 'New environment'}>
      <Stack>
        <Group grow><TextInput label="Code" required disabled={!!value.id} value={f.code} onChange={(e) => setF({ ...f, code: e.currentTarget.value.toUpperCase() })} /><TextInput label="Name" required value={f.name} onChange={(e) => setF({ ...f, name: e.currentTarget.value })} /><Switch mt="lg" label="Active" checked={f.active} onChange={(e) => setF({ ...f, active: e.currentTarget.checked })} /></Group>
        <Text size="sm" fw={600}>Approval and gates</Text>
        <Group>
          <Switch label="Approval required" checked={c.requires_approval} onChange={(e) => setC('requires_approval', e.currentTarget.checked)} />
          <NumberInput size="xs" w={140} label="Approvals" min={1} max={5} disabled={!c.requires_approval} value={c.approvals_required} onChange={(v) => setC('approvals_required', Number(v) || 1)} />
          <Switch label="Configuration must be approved" checked={c.require_config_approval} onChange={(e) => setC('require_config_approval', e.currentTarget.checked)} />
        </Group>
        <Group>
          <Switch label="Closed test run required" checked={c.require_test_run} onChange={(e) => setC('require_test_run', e.currentTarget.checked)} />
          <Switch label="Test run must be of the same build" checked={c.match_test_build} onChange={(e) => setC('match_test_build', e.currentTarget.checked)} />
          <Switch label="Verified repository commit required" checked={c.require_commit} onChange={(e) => setC('require_commit', e.currentTarget.checked)} />
        </Group>
        <Group grow>
          <MultiSelect label="Blocking open defect severities" data={['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']} value={c.blocking_defect_severities} onChange={(v) => setC('blocking_defect_severities', v)} />
          <TagsInput label="Required released document types (codes)" value={c.required_document_types} onChange={(v) => setC('required_document_types', v.map((x) => x.toUpperCase()))} />
        </Group>
        <TagsInput label="Release checklist" value={c.checklist} onChange={(v) => setC('checklist', v)} />
        <Group grow align="flex-end">
          <MultiSelect label="Change window days" data={DAYS.map((d, i) => ({ value: String(i), label: d }))} value={(c.change_window?.days || []).map(String)} onChange={(v) => setC('change_window', v.length ? { start: c.change_window?.start || '09:00', end: c.change_window?.end || '17:00', days: v.map(Number) } : null)} />
          <TextInput label="From (HH:MM)" disabled={!c.change_window} value={c.change_window?.start || ''} onChange={(e) => setC('change_window', { ...c.change_window, start: e.currentTarget.value })} />
          <TextInput label="To (HH:MM)" disabled={!c.change_window} value={c.change_window?.end || ''} onChange={(e) => setC('change_window', { ...c.change_window, end: e.currentTarget.value })} />
        </Group>
        <TagsInput label="Blackout dates (YYYY-MM-DD)" value={c.blackout_dates} onChange={(v) => setC('blackout_dates', v)} />
        <TagsInput label="Secrets (names; the server reads ELM_DEPLOY_SECRET_<NAME>)" value={c.secrets} onChange={(v) => setC('secrets', v.map((x) => x.toUpperCase()))} />
        <Text size="sm" fw={600}>Execution</Text>
        <Group grow>
          <Select label="Adapter" allowDeselect={false} value={c.adapter} onChange={(v) => setF({ ...f, config: { ...c, adapter: v, adapter_config: {} } })} data={[{ value: 'manual', label: 'Manual (operator records the result)' }, { value: 'gitlab_pipeline', label: 'GitLab pipeline' }, { value: 'script', label: 'Approved server script' }]} />
          {c.adapter === 'gitlab_pipeline' && <Select label="Repository" value={c.adapter_config.repository_id || null} onChange={(v) => setC('adapter_config', { ...c.adapter_config, repository_id: v })} data={(repos.data?.items || []).map((r: any) => ({ value: r.id, label: r.path }))} />}
          {c.adapter === 'script' && <TextInput label="Script file (in ELM_DEPLOY_SCRIPTS_DIR)" placeholder="deploy_uat.ps1" value={c.adapter_config.script || ''} onChange={(e) => setC('adapter_config', { script: e.currentTarget.value })} />}
        </Group>
        <Group grow align="flex-end">
          <TextInput label="Health check URL (optional, {version} allowed)" placeholder="http://uat-server/health" value={hc.url} onChange={(e) => setC('health_check', e.currentTarget.value ? { ...hc, url: e.currentTarget.value } : null)} />
          <NumberInput label="Expected status" w={130} disabled={!c.health_check} value={hc.expect_status} onChange={(v) => setC('health_check', { ...hc, expect_status: Number(v) })} />
          <NumberInput label="Retries" w={100} min={1} max={10} disabled={!c.health_check} value={hc.retries} onChange={(v) => setC('health_check', { ...hc, retries: Number(v) })} />
        </Group>
        {value.id && <Alert color="yellow" p="xs" icon={<IconAlertTriangle size={14} />}>Saving a changed configuration makes it a draft; someone else with approval rights must approve it before the next deployment.</Alert>}
        <Group justify="flex-end"><Button variant="default" onClick={onClose}>Cancel</Button><Button disabled={!f.code || f.name.length < 2} loading={save.isPending} onClick={() => save.mutate(undefined)}>Save</Button></Group>
      </Stack>
    </Modal>
  )
}
