import { ActionIcon, Alert, Anchor, Badge, Button, Card, Code, Drawer, FileInput, Group, Modal, MultiSelect, NumberInput, Progress, RingProgress, Select, SimpleGrid, Stack, Table, Tabs, Text, Textarea, TextInput, Tooltip } from '@mantine/core'
import { DateInput } from '@mantine/dates'
import { IconAlertTriangle, IconArrowLeft, IconCalendarEvent, IconChartBar, IconChevronDown, IconChevronRight, IconClockExclamation, IconDownload, IconFlag, IconGitCompare, IconLock, IconPencil, IconPlus, IconPlayerPlay, IconRoute, IconSitemap, IconTimeline, IconUpload, IconUsers } from '@tabler/icons-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { useAction, useDomains, useOrgUnits } from '../api/hooks'
import { EmptyBlock, Hash, Kpi, PageTitle, StatusTag, UserAvatar } from '../components/common'
import TaskDrawer, { PRIORITY_COLOR, type TaskTarget } from '../components/TaskDrawer'
import { UserSelect } from './InboxPage'

const iso = (d: Date | null) => (d ? dayjs(d).format('YYYY-MM-DD') : null)
const toDate = (s?: string | null) => (s ? new Date(s) : null)
const fmt = (s?: string | null) => (s ? dayjs(s).format('DD MMM YYYY') : '—')
const ACTIVITY_STATES = [{ value: 'NOT_STARTED', label: 'Not started' }, { value: 'IN_PROGRESS', label: 'In progress' }, { value: 'ON_HOLD', label: 'On hold' }, { value: 'COMPLETED', label: 'Completed' }, { value: 'CANCELLED', label: 'Cancelled' }]
const MILESTONE_STATES = [{ value: 'PLANNED', label: 'Planned' }, { value: 'IN_PROGRESS', label: 'In progress' }, { value: 'ACHIEVED', label: 'Achieved' }, { value: 'CANCELLED', label: 'Cancelled' }]

export default function PlanningPage() {
  const { projectId } = useParams()
  return projectId ? <ProjectPlanning key={projectId} projectId={projectId} /> : <Portfolio />
}

// ------------------------------------------------------------------ portfolio
function Portfolio() {
  const nav = useNavigate()
  const q = useQuery<any[]>({ queryKey: ['planning-portfolio'], queryFn: () => api.get('/planning/portfolio') })
  return (
    <div className="page">
      <PageTitle icon={<IconTimeline size={22} />} title="Planning" sub="Project plans, milestones, work packages and progress, for the projects you can see." />
      {q.data && !q.data.length && <EmptyBlock text="You are not assigned to any project yet." />}
      <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }}>
        {(q.data || []).map((row) => {
          const pl = row.plan
          return (
            <Card key={row.project.id} withBorder style={{ cursor: 'pointer' }} onClick={() => nav(`/planning/${row.project.id}`)}>
              <Group justify="space-between" wrap="nowrap">
                <div style={{ minWidth: 0 }}>
                  <Group gap={8}><span style={{ width: 10, height: 10, borderRadius: 3, background: row.project.color || '#2563eb' }} /><Text fw={700}>{row.project.code}</Text><StatusTag status={row.project.status} /></Group>
                  <Text size="sm" lineClamp={1}>{row.project.name}</Text>
                </div>
                {pl && <RingProgress size={64} thickness={6} roundCaps sections={[{ value: pl.progress, color: pl.progress >= 100 ? 'teal' : 'blue' }]} label={<Text ta="center" size="xs" fw={700}>{Math.round(pl.progress)}%</Text>} />}
              </Group>
              {pl ? (
                <>
                  <Text size="xs" c="dimmed" mt={6}>{pl.name} · v{pl.version_label}{pl.status === 'DRAFT' ? ' · draft' : ''}</Text>
                  <Group gap={6} mt="xs">
                    <Badge variant="light" size="sm">{pl.tasks} tasks</Badge>
                    {pl.overdue > 0 && <Badge color="red" variant="light" size="sm">{pl.overdue} overdue</Badge>}
                    {pl.open_gates > 0 && <Badge color="orange" variant="light" size="sm">{pl.open_gates} open gates</Badge>}
                  </Group>
                  {pl.next_milestone && <Text size="xs" mt="xs" c={pl.next_milestone.late ? 'red' : 'dimmed'}><IconFlag size={12} /> {pl.next_milestone.name}: {fmt(pl.next_milestone.due_date)}{pl.next_milestone.late ? ' (late)' : ''}</Text>}
                </>
              ) : <Text size="sm" c="dimmed" mt="sm">No plan yet{row.can_manage ? '. Open the project to create one.' : '.'}</Text>}
            </Card>
          )
        })}
      </SimpleGrid>
    </div>
  )
}

// ------------------------------------------------------------------ project
function ProjectPlanning({ projectId }: { projectId: string }) {
  const nav = useNavigate()
  const [sp, setSp] = useSearchParams()
  const plans = useQuery<any>({ queryKey: ['plans', projectId], queryFn: () => api.get(`/projects/${projectId}/plans`) })
  const items: any[] = plans.data?.items || []
  const chosen = sp.get('plan') || items.find((p) => p.status === 'ACTIVE')?.id || items[0]?.id || null
  const [editPlan, setEditPlan] = useState<any | null>(null)
  const canManage = !!plans.data?.can_manage
  const unplanned = useQuery<any[]>({ queryKey: ['work-items', 'project', projectId], queryFn: () => api.get('/work-items', { project_id: projectId, limit: 1000 }) })
  const loose = (unplanned.data || []).filter((t) => !t.plan).length
  const project = items[0]?.project
  return (
    <div className="page" style={{ maxWidth: 1800 }}>
      <Group mb="xs"><Anchor size="sm" component={Link} to="/planning"><IconArrowLeft size={13} /> All projects</Anchor></Group>
      <PageTitle icon={<IconTimeline size={22} />} title={project ? `${project.code} planning` : 'Project planning'} sub={project?.name}
        extra={<>
          {items.length > 0 && <Select w={280} value={chosen} onChange={(v) => { if (v) { sp.set('plan', v); setSp(sp, { replace: true }) } }} allowDeselect={false} data={items.map((p) => ({ value: p.id, label: `${p.name} (v${p.version_label}, ${p.status.toLowerCase()})` }))} />}
          {canManage && <Button variant={items.length ? 'default' : 'filled'} leftSection={<IconPlus size={16} />} onClick={() => setEditPlan({})}>New plan</Button>}
        </>} />
      {plans.isError && <Alert color="red" icon={<IconLock size={16} />}>You do not have access to this project.</Alert>}
      {loose > 0 && <Alert color="blue" mb="md" p="xs"><Group justify="space-between"><Text size="sm">{loose} task(s) in this project are not part of a plan.</Text><Button size="xs" variant="subtle" onClick={() => nav(`/tasks?project=${projectId}`)}>View on the board</Button></Group></Alert>}
      {plans.data && !items.length && <EmptyBlock text="This project has no plan yet." action={canManage ? <Button onClick={() => setEditPlan({})}>Create the first plan</Button> : undefined} />}
      {chosen && <PlanView key={chosen} planId={chosen} projectId={projectId} onEditPlan={setEditPlan} />}
      <PlanModal plan={editPlan} projectId={projectId} onClose={() => setEditPlan(null)} onCreated={(id) => { sp.set('plan', id); setSp(sp, { replace: true }) }} />
    </div>
  )
}

function PlanView({ planId, projectId, onEditPlan }: { planId: string; projectId: string; onEditPlan: (p: any) => void }) {
  const q = useQuery<any>({ queryKey: ['plan', planId], queryFn: () => api.get(`/plans/${planId}`) })
  const ov = useQuery<any>({ queryKey: ['plan-overview', planId], queryFn: () => api.get(`/plans/${planId}/overview`) })
  const [task, setTask] = useState<TaskTarget | null>(null)
  const refresh = [['plan', planId], ['plan-overview', planId], ['planning-portfolio'], ['plans', projectId]]
  const activate = useAction(() => api.post(`/plans/${planId}/activate`), { success: 'Plan activated', invalidate: refresh })
  if (q.isLoading || !q.data) return null
  const d = q.data
  const manage = d.can_manage && d.plan.status !== 'ARCHIVED'
  return (
    <>
      <Group mb="md" justify="space-between">
        <Group gap={8}><StatusTag status={d.plan.status} />{d.plan.owner && <><Text size="sm" c="dimmed">Owner</Text><UserAvatar user={d.plan.owner} size={22} showName /></>}</Group>
        <Group gap={8}>
          <Button component="a" href={`/api/v1/plans/${planId}/export.csv`} variant="default" size="xs" leftSection={<IconDownload size={14} />}>Export CSV</Button>
          {manage && <Button variant="default" size="xs" leftSection={<IconPencil size={14} />} onClick={() => onEditPlan(d.plan)}>Edit plan</Button>}
          {d.can_manage && d.plan.status === 'DRAFT' && <Button size="xs" leftSection={<IconPlayerPlay size={14} />} loading={activate.isPending} onClick={() => activate.mutate(undefined)}>Activate</Button>}
        </Group>
      </Group>
      <Tabs defaultValue="overview" keepMounted={false}>
        <Tabs.List mb="md">
          <Tabs.Tab value="overview" leftSection={<IconChartBar size={15} />}>Overview</Tabs.Tab>
          <Tabs.Tab value="wbs" leftSection={<IconSitemap size={15} />}>WBS</Tabs.Tab>
          <Tabs.Tab value="gantt" leftSection={<IconRoute size={15} />}>Gantt</Tabs.Tab>
          <Tabs.Tab value="milestones" leftSection={<IconFlag size={15} />}>Milestones ({d.milestones.length})</Tabs.Tab>
          <Tabs.Tab value="baselines" leftSection={<IconGitCompare size={15} />}>Baselines</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="overview"><Overview data={ov.data} onOpen={(id) => setTask({ id })} /></Tabs.Panel>
        <Tabs.Panel value="wbs"><Wbs plan={d} planId={planId} projectId={projectId} manage={manage} refresh={refresh} onOpen={setTask} /></Tabs.Panel>
        <Tabs.Panel value="gantt"><Gantt plan={d} onOpen={(id) => setTask({ id })} /></Tabs.Panel>
        <Tabs.Panel value="milestones"><Milestones plan={d} planId={planId} projectId={projectId} manage={manage} refresh={refresh} /></Tabs.Panel>
        <Tabs.Panel value="baselines"><Baselines planId={planId} manage={manage} /></Tabs.Panel>
      </Tabs>
      <TaskDrawer target={task} onClose={() => setTask(null)} invalidate={refresh} />
    </>
  )
}

// ------------------------------------------------------------------ overview
function Overview({ data, onOpen }: { data?: any; onOpen: (id: string) => void }) {
  if (!data) return null
  const t = data.tasks
  return (
    <Stack>
      {data.progress >= 100 && !data.fully_complete && <Alert color="orange" icon={<IconAlertTriangle size={16} />} title="Work is at 100%, but the plan is not complete">{data.open_gates.length} mandatory gate(s) are still open.</Alert>}
      <SimpleGrid cols={{ base: 2, md: 5 }}>
        <Kpi label="Progress" value={`${data.progress}%`} icon={<IconChartBar size={20} />} color="blue" hint={data.fully_complete ? 'All gates closed' : `${data.open_gates.length} open gates`} />
        <Kpi label="Tasks completed" value={`${t.completed} / ${t.total - t.cancelled}`} icon={<IconSitemap size={20} />} color="teal" hint={t.cancelled ? `${t.cancelled} cancelled` : undefined} />
        <Kpi label="Overdue tasks" value={t.overdue} icon={<IconClockExclamation size={20} />} color={t.overdue ? 'red' : 'gray'} />
        <Kpi label="Schedule conflicts" value={data.schedule_conflicts.length} icon={<IconRoute size={20} />} color={data.schedule_conflicts.length ? 'orange' : 'gray'} hint={`${data.critical_tasks} on critical path`} />
        <Kpi label="Cross-directorate links" value={data.cross_directorate_dependencies.length} icon={<IconUsers size={20} />} color="grape" />
      </SimpleGrid>
      <SimpleGrid cols={{ base: 1, lg: 2 }}>
        <Card withBorder>
          <Text fw={650} mb="sm">Progress by phase</Text>
          <Stack gap="sm">
            {data.phases.filter((p: any) => p.activities_total).map((p: any) => (
              <div key={p.id || 'none'}>
                <Group justify="space-between" mb={3}><Text size="sm" fw={550}>{p.name}</Text><Text size="xs" c="dimmed">{p.activities_completed}/{p.activities_total} activities · {p.open_tasks} open tasks · weight {p.weight} · <b>{p.progress}%</b></Text></Group>
                <Progress value={p.progress} size="sm" color={p.late_activities ? 'orange' : p.progress >= 100 ? 'teal' : 'blue'} />
              </div>
            ))}
            {!data.phases.some((p: any) => p.activities_total) && <Text size="sm" c="dimmed">No activities yet.</Text>}
          </Stack>
          <Text size="xs" c="dimmed" mt="md">{data.calculation.rule}</Text>
        </Card>
        <Card withBorder>
          <Text fw={650} mb="sm">Tasks by status</Text>
          {t.total > 0 && <Progress.Root size={18} mb="sm">{t.by_status.filter((s: any) => s.count).map((s: any) => <Tooltip key={s.status} label={`${s.label}: ${s.count}`}><Progress.Section value={(s.count / t.total) * 100} color={s.color}><Progress.Label>{s.count}</Progress.Label></Progress.Section></Tooltip>)}</Progress.Root>}
          <Group gap="xs">{t.by_status.filter((s: any) => s.count).map((s: any) => <Badge key={s.status} variant="light" color={s.color}>{s.label}: {s.count}</Badge>)}</Group>
          <Text fw={650} mt="lg" mb="xs">Workload (open tasks)</Text>
          {data.workload.length ? (
            <Table verticalSpacing={4}><Table.Tbody>{data.workload.slice(0, 8).map((w: any) => <Table.Tr key={w.user?.id}><Table.Td><UserAvatar user={w.user} size={22} showName /></Table.Td><Table.Td ta="right"><Text size="xs">{w.open} open{w.late ? <Text span c="red" size="xs"> · {w.late} late</Text> : ''}</Text></Table.Td><Table.Td ta="right"><Text size="xs" c="dimmed">{w.estimated_hours} h</Text></Table.Td></Table.Tr>)}</Table.Tbody></Table>
          ) : <Text size="sm" c="dimmed">No open assigned tasks.</Text>}
        </Card>
        <Card withBorder>
          <Text fw={650} mb="sm">Overdue</Text>
          {data.overdue.length ? <Stack gap={6}>{data.overdue.slice(0, 8).map((o: any) => <Group key={o.id} justify="space-between" wrap="nowrap" style={{ cursor: 'pointer' }} onClick={() => onOpen(o.id)}><Text size="sm" lineClamp={1}><b>{o.key}</b> {o.title}</Text><Badge color="red" variant="light" style={{ flexShrink: 0 }}>{o.days_late} d late</Badge></Group>)}</Stack> : <Text size="sm" c="dimmed">Nothing is overdue.</Text>}
        </Card>
        <Card withBorder>
          <Text fw={650} mb="sm">Open gates and risks</Text>
          <Stack gap={6}>
            {data.open_gates.map((g: any, i: number) => <Text key={i} size="sm" c={g.late ? 'red' : undefined}>{g.type === 'MILESTONE' ? <><IconFlag size={13} /> {g.name}: due {fmt(g.due_date)}</> : <><IconLock size={13} /> {g.document} is {g.status}, must be {g.required} ({g.task})</>}</Text>)}
            {data.schedule_conflicts.map((c: any, i: number) => <Text key={`c${i}`} size="sm" c="orange"><IconAlertTriangle size={13} /> {c.message}</Text>)}
            {data.cross_directorate_dependencies.map((c: any, i: number) => <Text key={`x${i}`} size="sm"><IconUsers size={13} /> {c.successor} ({c.successor_org?.code}, {c.successor_owner?.full_name || 'no owner'}) waits on {c.predecessor} ({c.predecessor_org?.code}, {c.predecessor_owner?.full_name || 'no owner'})</Text>)}
            {!data.open_gates.length && !data.schedule_conflicts.length && !data.cross_directorate_dependencies.length && <Text size="sm" c="dimmed">None.</Text>}
          </Stack>
        </Card>
      </SimpleGrid>
    </Stack>
  )
}

// ------------------------------------------------------------------ WBS
function Wbs({ plan, planId, projectId, manage, refresh, onOpen }: { plan: any; planId: string; projectId: string; manage: boolean; refresh: any[][]; onOpen: (t: TaskTarget) => void }) {
  const [wp, setWp] = useState<any | null>(null)
  const [act, setAct] = useState<any | null>(null)
  const [imp, setImp] = useState(false)
  const [closed, setClosed] = useState<Record<string, boolean>>({})
  const toggle = (k: string) => setClosed((c) => ({ ...c, [k]: !c[k] }))
  const childrenOf = useMemo(() => {
    const m: Record<string, any[]> = {}
    plan.tasks.forEach((t: any) => { if (t.parent_id) (m[t.parent_id] ||= []).push(t) })
    return m
  }, [plan.tasks])
  const present = new Set(plan.tasks.map((t: any) => t.id))
  const topTasks = (a: any) => plan.tasks.filter((t: any) => t.activity_id === a.id && (!t.parent_id || !present.has(t.parent_id)))
  const taskRows = (t: any, depth: number): JSX.Element[] => [
    <Table.Tr key={t.id} style={{ cursor: 'pointer' }} onClick={() => onOpen({ id: t.id })}>
      <Table.Td style={{ paddingLeft: 12 + depth * 22 }}><Group gap={6} wrap="nowrap"><Text size="xs" c="dimmed" fw={600} style={{ whiteSpace: 'nowrap' }}>{t.key}</Text><Text size="sm" lineClamp={1}>{t.title}</Text>{t.critical && <Tooltip label="On the critical path"><Badge size="xs" color="red" variant="dot">critical</Badge></Tooltip>}</Group></Table.Td>
      <Table.Td><UserAvatar user={t.assignee} size={22} /></Table.Td>
      <Table.Td><Badge size="xs" color={t.status_color} variant="light">{t.status_label}</Badge></Table.Td>
      <Table.Td><Badge size="xs" color={PRIORITY_COLOR[t.priority]} variant="light">{t.priority}</Badge></Table.Td>
      <Table.Td><Text size="xs" c={t.late ? 'red' : undefined} style={{ whiteSpace: 'nowrap' }}>{fmt(t.start_date)} – {fmt(t.end_date)}</Text></Table.Td>
      <Table.Td ta="right"><Text size="xs">{t.estimated_hours || 0} h</Text></Table.Td>
      <Table.Td w={130}><Group gap={6} wrap="nowrap"><Progress value={t.progress} size="sm" style={{ flex: 1 }} /><Text size="xs" w={34} ta="right">{Math.round(t.progress)}%</Text></Group></Table.Td>
      <Table.Td />
    </Table.Tr>,
    ...(childrenOf[t.id] || []).flatMap((c) => taskRows(c, depth + 1)),
  ]
  const activityRows = (a: any, depth: number) => {
    const open = !closed[a.id]
    return [
      <Table.Tr key={a.id} style={{ background: 'var(--elm-soft)' }}>
        <Table.Td style={{ paddingLeft: 12 + depth * 22 }}><Group gap={4} wrap="nowrap"><ActionIcon size="xs" variant="subtle" color="gray" aria-label={open ? 'Collapse' : 'Expand'} onClick={() => toggle(a.id)}>{open ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}</ActionIcon><Text size="sm" fw={600} lineClamp={1}>{a.title}</Text>{a.phase && <Badge size="xs" variant="outline" color="gray">{a.phase}</Badge>}</Group></Table.Td>
        <Table.Td><UserAvatar user={a.owner} size={22} /></Table.Td>
        <Table.Td><StatusTag status={a.status} /></Table.Td>
        <Table.Td />
        <Table.Td><Text size="xs" c={a.late ? 'red' : undefined} style={{ whiteSpace: 'nowrap' }}>{fmt(a.start_date)} – {fmt(a.end_date)}</Text></Table.Td>
        <Table.Td ta="right"><Text size="xs">{a.estimated_hours || 0} h</Text></Table.Td>
        <Table.Td><Group gap={6} wrap="nowrap"><Progress value={a.progress} size="sm" color="indigo" style={{ flex: 1 }} /><Text size="xs" w={34} ta="right">{Math.round(a.progress)}%</Text></Group></Table.Td>
        <Table.Td ta="right">{manage && <Group gap={2} justify="flex-end" wrap="nowrap"><Tooltip label="Add a task"><ActionIcon size="sm" variant="subtle" aria-label="Add a task" onClick={() => onOpen({ defaults: { project_id: projectId, activity_id: a.id, plan_id: planId, start_date: a.start_date, due_date: a.end_date } })}><IconPlus size={14} /></ActionIcon></Tooltip><ActionIcon size="sm" variant="subtle" color="gray" aria-label="Edit activity" onClick={() => setAct(a)}><IconPencil size={14} /></ActionIcon></Group>}</Table.Td>
      </Table.Tr>,
      ...(open ? topTasks(a).flatMap((t: any) => taskRows(t, depth + 1)) : []),
    ]
  }
  const noPackage = plan.activities.filter((a: any) => !a.work_package_id)
  const looseTasks = plan.tasks.filter((t: any) => !t.activity_id && (!t.parent_id || !present.has(t.parent_id)))
  return (
    <Stack>
      {manage && (
        <Group gap="xs">
          <Button size="xs" variant="light" leftSection={<IconPlus size={14} />} onClick={() => setWp({})}>Work package</Button>
          <Button size="xs" variant="light" leftSection={<IconPlus size={14} />} onClick={() => setAct({})}>Activity</Button>
          <Button size="xs" variant="light" leftSection={<IconPlus size={14} />} onClick={() => onOpen({ defaults: { project_id: projectId, plan_id: planId } })}>Task</Button>
          <Button size="xs" variant="default" leftSection={<IconUpload size={14} />} onClick={() => setImp(true)}>Import CSV</Button>
        </Group>
      )}
      {!plan.work_packages.length && !plan.activities.length && !plan.tasks.length ? <EmptyBlock text="This plan is empty. Add a work package or an activity to begin." /> : (
        <Card withBorder p={0} style={{ overflowX: 'auto' }}>
          <Table highlightOnHover verticalSpacing={6} miw={980}>
            <Table.Thead><Table.Tr><Table.Th>Work breakdown</Table.Th><Table.Th>Owner</Table.Th><Table.Th>Status</Table.Th><Table.Th>Priority</Table.Th><Table.Th>Dates</Table.Th><Table.Th ta="right">Est.</Table.Th><Table.Th>Progress</Table.Th><Table.Th /></Table.Tr></Table.Thead>
            <Table.Tbody>
              {plan.work_packages.flatMap((w: any) => {
                const open = !closed[w.id]
                return [
                  <Table.Tr key={w.id} style={{ background: 'color-mix(in srgb, #2563eb 7%, var(--elm-surface))' }}>
                    <Table.Td><Group gap={4} wrap="nowrap"><ActionIcon size="xs" variant="subtle" color="gray" aria-label={open ? 'Collapse' : 'Expand'} onClick={() => toggle(w.id)}>{open ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}</ActionIcon><Badge size="sm" color="indigo">{w.code}</Badge><Text size="sm" fw={700} lineClamp={1}>{w.name}</Text>{w.lead_org && <Badge size="xs" variant="light" color="blue">{w.lead_org.code}</Badge>}{w.contributors.map((c: any) => <Badge key={c.id} size="xs" variant="outline" color="gray">{c.code}</Badge>)}</Group></Table.Td>
                    <Table.Td><UserAvatar user={w.owner} size={22} /></Table.Td>
                    <Table.Td><StatusTag status={w.status} /></Table.Td>
                    <Table.Td />
                    <Table.Td><Text size="xs" style={{ whiteSpace: 'nowrap' }}>{fmt(w.start_date)} – {fmt(w.end_date)}</Text></Table.Td>
                    <Table.Td />
                    <Table.Td><Group gap={6} wrap="nowrap"><Progress value={w.progress} size="sm" color="grape" style={{ flex: 1 }} /><Text size="xs" w={34} ta="right">{Math.round(w.progress)}%</Text></Group></Table.Td>
                    <Table.Td ta="right">{manage && <ActionIcon size="sm" variant="subtle" color="gray" aria-label="Edit work package" onClick={() => setWp(w)}><IconPencil size={14} /></ActionIcon>}</Table.Td>
                  </Table.Tr>,
                  ...(open ? plan.activities.filter((a: any) => a.work_package_id === w.id).flatMap((a: any) => activityRows(a, 1)) : []),
                ]
              })}
              {noPackage.flatMap((a: any) => activityRows(a, 0))}
              {looseTasks.flatMap((t: any) => taskRows(t, 0))}
            </Table.Tbody>
          </Table>
        </Card>
      )}
      <WorkPackageModal value={wp} plan={plan} planId={planId} projectId={projectId} refresh={refresh} onClose={() => setWp(null)} />
      <ActivityModal value={act} plan={plan} planId={planId} refresh={refresh} onClose={() => setAct(null)} />
      <ImportModal opened={imp} planId={planId} refresh={refresh} onClose={() => setImp(false)} />
    </Stack>
  )
}

// ------------------------------------------------------------------ Gantt
const ROW = 30
const DAY_MIN = 4
function Gantt({ plan, onOpen }: { plan: any; onOpen: (id: string) => void }) {
  const [zoom, setZoom] = useState(8)
  const scrolled = useRef(false)
  const rows = useMemo(() => {
    const out: any[] = []
    const seen = new Set<string>()
    const addTasks = (list: any[]) => list.forEach((t) => { seen.add(t.id); out.push({ ...t, kind: 'task' }) })
    plan.activities.forEach((a: any) => { out.push({ ...a, kind: 'activity' }); addTasks(plan.tasks.filter((t: any) => t.activity_id === a.id)) })
    addTasks(plan.tasks.filter((t: any) => !seen.has(t.id)))
    return out
  }, [plan])
  const dates = [...rows.flatMap((r) => [r.start_date, r.end_date]), ...plan.milestones.map((m: any) => m.due_date)].filter(Boolean).map((d: string) => dayjs(d))
  const scheduled = rows.filter((r) => r.start_date || r.end_date).length
  if (!dates.length) return <EmptyBlock text="No dates to show yet. Give activities or tasks a start and due date." />
  const min = dates.reduce((a, b) => (b.isBefore(a) ? b : a)).subtract(7, 'day').startOf('month')
  const max = dates.reduce((a, b) => (b.isAfter(a) ? b : a)).add(14, 'day').endOf('month')
  const days = max.diff(min, 'day') + 1
  const dayW = Math.max(DAY_MIN, zoom)
  const width = days * dayW
  const x = (d: string) => dayjs(d).diff(min, 'day') * dayW
  const today = dayjs().isAfter(min) && dayjs().isBefore(max) ? x(dayjs().format('YYYY-MM-DD')) : null
  const months: { x: number; w: number; label: string }[] = []
  for (let m = min.startOf('month'); m.isBefore(max); m = m.add(1, 'month')) {
    const from = m.isBefore(min) ? min : m
    const end = m.endOf('month').isAfter(max) ? max : m.endOf('month')
    months.push({ x: from.diff(min, 'day') * dayW, w: (end.diff(from, 'day') + 1) * dayW, label: from.format(dayW < 6 ? 'MMM YY' : 'MMM YYYY') })
  }
  // Open on today rather than on the plan's first month, once only so zooming does not jump.
  const openOnToday = (el: HTMLDivElement | null) => {
    if (el && today !== null && !scrolled.current) { el.scrollLeft = Math.max(today - 120, 0); scrolled.current = true }
  }
  const headH = 26
  const msH = plan.milestones.length ? 26 : 0
  const top = (i: number) => headH + msH + i * ROW
  const height = top(rows.length) + 6
  const rowIndex = new Map(rows.map((r, i) => [r.id, i]))
  const bounds = (r: any) => {
    const s = r.start_date || r.end_date
    const e = r.end_date || r.start_date
    return s && e ? { x1: x(s), x2: x(e) + dayW } : null
  }
  const arrows = plan.dependencies.map((d: any) => {
    const si = rowIndex.get(d.successor_id), pi = rowIndex.get(d.predecessor_id)
    if (si === undefined || pi === undefined) return null
    const sb = bounds(rows[si]), pb = bounds(rows[pi])
    if (!sb || !pb) return null
    const fromX = d.type === 'SS' || d.type === 'SF' ? pb.x1 : pb.x2
    const toX = d.type === 'FF' || d.type === 'SF' ? sb.x2 : sb.x1
    const y1 = top(pi) + ROW / 2, y2 = top(si) + ROW / 2
    const mid = Math.min(fromX, toX) - 8
    const elbow = toX > fromX + 12 ? `H ${toX - 8}` : `H ${fromX + 6} V ${(y1 + y2) / 2} H ${mid}`
    return <path key={d.id} d={`M ${fromX} ${y1} ${elbow} V ${y2} H ${toX - 1}`} fill="none" stroke="var(--mantine-color-gray-6)" strokeWidth={1.1} markerEnd="url(#elm-arrow)" />
  })
  return (
    <Stack gap="xs">
      <Group justify="space-between">
        <Group gap="md">
          <Group gap={5}><span style={{ width: 14, height: 8, borderRadius: 2, background: 'var(--mantine-color-blue-6)' }} /><Text size="xs" c="dimmed">Task</Text></Group>
          <Group gap={5}><span style={{ width: 14, height: 8, borderRadius: 2, background: 'var(--mantine-color-indigo-3)' }} /><Text size="xs" c="dimmed">Activity</Text></Group>
          <Group gap={5}><span style={{ width: 14, height: 8, borderRadius: 2, outline: '2px solid var(--mantine-color-red-6)' }} /><Text size="xs" c="dimmed">Critical path</Text></Group>
          <Group gap={5}><IconFlag size={13} color="var(--mantine-color-orange-6)" /><Text size="xs" c="dimmed">Milestone</Text></Group>
          {scheduled < rows.length && <Text size="xs" c="dimmed">{rows.length - scheduled} row(s) have no dates.</Text>}
        </Group>
        <Group gap={4}><Text size="xs" c="dimmed">Zoom</Text><Button size="compact-xs" variant="default" onClick={() => setZoom((z) => Math.max(DAY_MIN, z - 2))}>−</Button><Button size="compact-xs" variant="default" onClick={() => setZoom((z) => Math.min(30, z + 2))}>+</Button></Group>
      </Group>
      <Card withBorder p={0} ref={openOnToday} style={{ overflow: 'auto', maxHeight: '72vh' }}>
        <div style={{ display: 'flex', minWidth: 'max-content' }}>
          <div style={{ width: 300, flexShrink: 0, position: 'sticky', left: 0, zIndex: 2, background: 'var(--elm-surface)', borderRight: '1px solid var(--elm-border)' }}>
            <div style={{ height: headH + msH, borderBottom: '1px solid var(--elm-border)', display: 'flex', alignItems: 'center', paddingLeft: 10 }}><Text size="xs" fw={700} c="dimmed">Activity / task</Text></div>
            {rows.map((r) => (
              <div key={`${r.kind}${r.id}`} title={r.title} onClick={() => r.kind === 'task' && onOpen(r.id)} style={{ height: ROW, display: 'flex', alignItems: 'center', gap: 6, padding: r.kind === 'task' ? '0 8px 0 22px' : '0 8px 0 10px', cursor: r.kind === 'task' ? 'pointer' : 'default', borderBottom: '1px solid var(--elm-border)', background: r.kind === 'activity' ? 'var(--elm-soft)' : undefined }}>
                {r.kind === 'task' && <Text size="xs" c="dimmed" fw={600} style={{ whiteSpace: 'nowrap' }}>{r.key}</Text>}
                <Text size="xs" fw={r.kind === 'activity' ? 650 : 400} truncate>{r.title}</Text>
              </div>
            ))}
          </div>
          <svg width={width} height={height} role="img" aria-label="Gantt chart of the plan" style={{ display: 'block', flexShrink: 0 }}>
            <defs><marker id="elm-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0 L8 4 L0 8 z" fill="var(--mantine-color-gray-6)" /></marker></defs>
            {months.map((m) => <g key={m.x}><line x1={m.x} x2={m.x} y1={0} y2={height} stroke="var(--elm-border)" /><text x={m.x + 6} y={17} fontSize={11} fontWeight={600} fill="var(--mantine-color-dimmed)">{m.w > 44 ? m.label : ''}</text></g>)}
            <line x1={0} x2={width} y1={headH + msH} y2={headH + msH} stroke="var(--elm-border)" />
            {rows.map((r, i) => <rect key={`bg${r.kind}${r.id}`} x={0} y={top(i)} width={width} height={ROW} fill={r.kind === 'activity' ? 'var(--elm-soft)' : 'transparent'} stroke="var(--elm-border)" strokeWidth={0.5} />)}
            {today !== null && <g><line x1={today} x2={today} y1={0} y2={height} stroke="var(--mantine-color-red-5)" strokeDasharray="4 3" /><text x={today + 4} y={height - 4} fontSize={10} fill="var(--mantine-color-red-6)">Today</text></g>}
            {plan.milestones.filter((m: any) => m.due_date).map((m: any) => {
              const mx = x(m.due_date)
              const color = m.status === 'ACHIEVED' ? 'var(--mantine-color-teal-6)' : m.late ? 'var(--mantine-color-red-6)' : 'var(--mantine-color-orange-6)'
              return <g key={m.id}><title>{`${m.name}: ${fmt(m.due_date)} (${m.status.toLowerCase()})`}</title><line x1={mx} x2={mx} y1={headH + 12} y2={height} stroke={color} strokeOpacity={0.35} /><path d={`M ${mx} ${headH + 4} l 6 7 l -6 7 l -6 -7 z`} fill={color} /><text x={mx + 9} y={headH + 15} fontSize={10.5} fill={color}>{dayW >= 6 ? m.code || m.name : ''}</text></g>
            })}
            {arrows}
            {rows.map((r, i) => {
              const b = bounds(r)
              if (!b) return null
              const w = Math.max(b.x2 - b.x1, 3)
              const y = top(i) + (r.kind === 'activity' ? 9 : 6)
              const h = r.kind === 'activity' ? 12 : 18
              const color = r.kind === 'activity' ? 'var(--mantine-color-indigo-3)' : `var(--mantine-color-${r.status_color || 'blue'}-${r.status_color === 'gray' ? 4 : 2})`
              const fill = r.kind === 'activity' ? 'var(--mantine-color-indigo-6)' : `var(--mantine-color-${r.status_color || 'blue'}-6)`
              return (
                <g key={`bar${r.kind}${r.id}`} onClick={() => r.kind === 'task' && onOpen(r.id)} style={{ cursor: r.kind === 'task' ? 'pointer' : 'default' }}>
                  <title>{`${r.key ? r.key + ' ' : ''}${r.title}\n${fmt(r.start_date)} – ${fmt(r.end_date)}\n${Math.round(r.progress)}% complete`}</title>
                  <rect x={b.x1} y={y} width={w} height={h} rx={3} fill={color} stroke={r.critical ? 'var(--mantine-color-red-6)' : r.late ? 'var(--mantine-color-red-4)' : 'none'} strokeWidth={r.critical ? 2 : 1} />
                  <rect x={b.x1} y={y} width={(w * Math.min(r.progress, 100)) / 100} height={h} rx={3} fill={fill} />
                </g>
              )
            })}
          </svg>
        </div>
      </Card>
    </Stack>
  )
}

// ------------------------------------------------------------------ milestones
function Milestones({ plan, planId, projectId, manage, refresh }: { plan: any; planId: string; projectId: string; manage: boolean; refresh: any[][] }) {
  const [edit, setEdit] = useState<any | null>(null)
  return (
    <Stack>
      {manage && <Group><Button size="xs" variant="light" leftSection={<IconPlus size={14} />} onClick={() => setEdit({})}>Milestone</Button></Group>}
      {!plan.milestones.length ? <EmptyBlock text="No milestones yet." icon={<IconFlag size={26} />} /> : (
        <Card withBorder p={0}>
          <Table verticalSpacing={8} highlightOnHover>
            <Table.Thead><Table.Tr><Table.Th>Milestone</Table.Th><Table.Th>Status</Table.Th><Table.Th>Due</Table.Th><Table.Th>Achieved</Table.Th><Table.Th>Owner</Table.Th><Table.Th /></Table.Tr></Table.Thead>
            <Table.Tbody>
              {plan.milestones.map((m: any) => (
                <Table.Tr key={m.id}>
                  <Table.Td><Group gap={6}><IconFlag size={14} color={m.late ? 'var(--mantine-color-red-6)' : 'var(--mantine-color-orange-6)'} />{m.code && <Badge size="xs" variant="outline" color="gray">{m.code}</Badge>}<Text size="sm" fw={550}>{m.name}</Text></Group></Table.Td>
                  <Table.Td><Group gap={4}><StatusTag status={m.status} />{m.late && <Badge size="xs" color="red">Late</Badge>}{m.at_risk && !m.late && <Badge size="xs" color="orange" variant="light">Due soon</Badge>}</Group></Table.Td>
                  <Table.Td><Text size="sm">{fmt(m.due_date)}</Text></Table.Td>
                  <Table.Td><Text size="sm">{fmt(m.achieved_date)}</Text></Table.Td>
                  <Table.Td><UserAvatar user={m.owner} size={22} showName /></Table.Td>
                  <Table.Td ta="right">{manage && <ActionIcon size="sm" variant="subtle" color="gray" aria-label="Edit milestone" onClick={() => setEdit(m)}><IconPencil size={14} /></ActionIcon>}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Card>
      )}
      <MilestoneModal value={edit} planId={planId} projectId={projectId} refresh={refresh} onClose={() => setEdit(null)} plan={plan} />
    </Stack>
  )
}

function MilestoneModal({ value, planId, projectId, refresh, onClose }: { value: any | null; plan: any; planId: string; projectId: string; refresh: any[][]; onClose: () => void }) {
  const [f, setF] = useState<any>({})
  useEffect(() => { if (value) setF({ name: value.name || '', code: value.code || '', description: value.description || '', start_date: value.start_date || null, due_date: value.due_date || null, achieved_date: value.achieved_date || null, status: value.status || 'PLANNED', owner_id: value.owner?.id || null, plan_id: value.plan_id ?? planId, org_unit_id: value.org_unit_id || null, item_id: value.item_id || null, reason: '' }) }, [value])
  const set = (k: string) => (v: any) => setF((x: any) => ({ ...x, [k]: v }))
  const isNew = value && !value.id
  const moved = !isNew && value?.due_date && value.due_date !== f.due_date
  const save = useAction(() => (isNew ? api.post(`/projects/${projectId}/milestones`, f) : api.put(`/milestones/${value.id}`, f, { version: value.version })), { success: 'Milestone saved', invalidate: refresh, onDone: onClose })
  return (
    <Modal opened={!!value} onClose={onClose} title={isNew ? 'New milestone' : 'Edit milestone'}>
      <Stack>
        <TextInput label="Name" required value={f.name || ''} onChange={(e) => set('name')(e.currentTarget.value)} />
        <Group grow><TextInput label="Code" value={f.code || ''} onChange={(e) => set('code')(e.currentTarget.value)} /><Select label="Status" allowDeselect={false} value={f.status} onChange={set('status')} data={MILESTONE_STATES} /></Group>
        <Group grow><DateInput label="Start" clearable value={toDate(f.start_date)} onChange={(d) => set('start_date')(iso(d))} /><DateInput label="Due" clearable value={toDate(f.due_date)} onChange={(d) => set('due_date')(iso(d))} /></Group>
        <UserSelect label="Owner" value={f.owner_id} onChange={set('owner_id')} />
        {moved && <Textarea label="Reason for moving the due date" required autosize value={f.reason || ''} onChange={(e) => set('reason')(e.currentTarget.value)} />}
        <Group justify="flex-end"><Button variant="default" onClick={onClose}>Cancel</Button><Button disabled={(f.name || '').length < 2 || (moved && !(f.reason || '').trim())} loading={save.isPending} onClick={() => save.mutate(undefined)}>Save</Button></Group>
      </Stack>
    </Modal>
  )
}

// ------------------------------------------------------------------ baselines
function Baselines({ planId, manage }: { planId: string; manage: boolean }) {
  const q = useQuery<any[]>({ queryKey: ['baselines', planId], queryFn: () => api.get(`/plans/${planId}/baselines`) })
  const [open, setOpen] = useState(false)
  const [label, setLabel] = useState('')
  const [reason, setReason] = useState('')
  const [compare, setCompare] = useState<string | null>(null)
  const create = useAction(() => api.post(`/plans/${planId}/baselines`, { label, reason }), { success: 'Baseline captured', invalidate: [['baselines', planId]], onDone: () => { setOpen(false); setLabel(''); setReason('') } })
  return (
    <Stack>
      <Text size="sm" c="dimmed">A baseline is a sealed snapshot of the plan's dates and scope. Later changes never alter it, so slippage can always be measured against it.</Text>
      {manage && <Group><Button size="xs" variant="light" leftSection={<IconLock size={14} />} onClick={() => setOpen(true)}>Capture baseline</Button></Group>}
      {q.data && !q.data.length && <EmptyBlock text="No baselines yet." icon={<IconCalendarEvent size={26} />} />}
      {!!q.data?.length && (
        <Card withBorder p={0}>
          <Table verticalSpacing={8}>
            <Table.Thead><Table.Tr><Table.Th>#</Table.Th><Table.Th>Label</Table.Th><Table.Th>Reason</Table.Th><Table.Th>Captured</Table.Th><Table.Th>SHA-256</Table.Th><Table.Th /></Table.Tr></Table.Thead>
            <Table.Tbody>{q.data.map((b) => <Table.Tr key={b.id}><Table.Td>{b.seq}</Table.Td><Table.Td><Text size="sm" fw={600}>{b.label}</Text></Table.Td><Table.Td><Text size="sm" lineClamp={2}>{b.reason}</Text></Table.Td><Table.Td><Text size="xs">{fmt(b.created_at)}{b.created_by ? ` · ${b.created_by.full_name}` : ''}</Text></Table.Td><Table.Td><Hash value={b.sha256} /></Table.Td><Table.Td ta="right"><Button size="xs" variant="subtle" onClick={() => setCompare(b.id)}>Compare</Button></Table.Td></Table.Tr>)}</Table.Tbody>
          </Table>
        </Card>
      )}
      <Modal opened={open} onClose={() => setOpen(false)} title="Capture baseline">
        <Stack>
          <TextInput label="Label" required placeholder="e.g. PDR baseline" value={label} onChange={(e) => setLabel(e.currentTarget.value)} />
          <Textarea label="Reason" required autosize minRows={2} value={reason} onChange={(e) => setReason(e.currentTarget.value)} />
          <Group justify="flex-end"><Button variant="default" onClick={() => setOpen(false)}>Cancel</Button><Button disabled={label.length < 2 || reason.length < 3} loading={create.isPending} onClick={() => create.mutate(undefined)}>Capture</Button></Group>
        </Stack>
      </Modal>
      <CompareDrawer id={compare} onClose={() => setCompare(null)} />
    </Stack>
  )
}

function CompareDrawer({ id, onClose }: { id: string | null; onClose: () => void }) {
  const q = useQuery<any>({ queryKey: ['baseline-compare', id], queryFn: () => api.get(`/baselines/${id}/compare`), enabled: !!id })
  const d = q.data
  const section = (title: string, s: any) => (
    <div key={title}>
      <Group gap={6} mb={6}><Text fw={650} size="sm">{title}</Text><Badge size="xs" variant="light" color="orange">{s.moved.length} moved</Badge><Badge size="xs" variant="light" color="teal">{s.added.length} added</Badge><Badge size="xs" variant="light" color="red">{s.removed.length} removed</Badge></Group>
      {s.moved.map((m: any) => <Group key={m.id} justify="space-between" wrap="nowrap"><Text size="xs" lineClamp={1}>{m.name}</Text><Text size="xs" c={m.slip_days > 0 ? 'red' : 'teal'} style={{ whiteSpace: 'nowrap' }}>{fmt(m.baseline)} → {fmt(m.current)}{m.slip_days != null ? ` (${m.slip_days > 0 ? '+' : ''}${m.slip_days} d)` : ''}</Text></Group>)}
      {s.added.map((a: any) => <Text key={a.id} size="xs" c="teal">+ {a.key || a.title || a.name}</Text>)}
      {s.removed.map((a: any) => <Text key={a.id} size="xs" c="red">− {a.key || a.title || a.name}</Text>)}
    </div>
  )
  return (
    <Drawer opened={!!id} onClose={onClose} position="right" size={560} title={<Text fw={650}>Baseline {d?.baseline?.seq}: {d?.baseline?.label}</Text>}>
      {d && (
        <Stack>
          <Alert color={d.integrity_ok ? 'teal' : 'red'} p="xs" icon={d.integrity_ok ? <IconLock size={16} /> : <IconAlertTriangle size={16} />}>{d.integrity_ok ? 'The seal is intact: this snapshot has not changed since it was captured.' : 'The seal does not match. This snapshot has been altered.'}</Alert>
          {section('Tasks', d.tasks)}
          {section('Activities', d.activities)}
          {section('Milestones', d.milestones)}
        </Stack>
      )}
    </Drawer>
  )
}

// ------------------------------------------------------------------ forms
function PlanModal({ plan, projectId, onClose, onCreated }: { plan: any | null; projectId: string; onClose: () => void; onCreated: (id: string) => void }) {
  const [f, setF] = useState<any>({})
  useEffect(() => { if (plan) setF({ name: plan.name || '', version_label: plan.version_label || '1.0', description: plan.description || '', owner_id: plan.owner?.id || null }) }, [plan])
  const qc = useQueryClient()
  const isNew = plan && !plan.id
  const save = useAction(() => (isNew ? api.post(`/projects/${projectId}/plans`, f) : api.put(`/plans/${plan.id}`, f, { version: plan.version })), { success: 'Plan saved', invalidate: [['plans', projectId], ['planning-portfolio']],
    onDone: (r: any) => { if (isNew) onCreated(r.id); else qc.invalidateQueries({ queryKey: ['plan', plan.id] }); onClose() } })
  const set = (k: string) => (v: any) => setF((x: any) => ({ ...x, [k]: v }))
  return (
    <Modal opened={!!plan} onClose={onClose} title={isNew ? 'New plan' : 'Edit plan'}>
      <Stack>
        <TextInput label="Name" required value={f.name || ''} onChange={(e) => set('name')(e.currentTarget.value)} />
        <TextInput label="Version" value={f.version_label || ''} onChange={(e) => set('version_label')(e.currentTarget.value)} />
        <UserSelect label="Owner" value={f.owner_id} onChange={set('owner_id')} />
        <Textarea label="Description" autosize minRows={2} value={f.description || ''} onChange={(e) => set('description')(e.currentTarget.value)} />
        <Group justify="flex-end"><Button variant="default" onClick={onClose}>Cancel</Button><Button disabled={(f.name || '').length < 2} loading={save.isPending} onClick={() => save.mutate(undefined)}>Save</Button></Group>
      </Stack>
    </Modal>
  )
}

function WorkPackageModal({ value, planId, projectId, refresh, onClose }: { value: any | null; plan: any; planId: string; projectId: string; refresh: any[][]; onClose: () => void }) {
  const orgs = useOrgUnits()
  const domains = useDomains()
  const tree = useQuery<any>({ queryKey: ['tree', projectId], queryFn: () => api.get(`/projects/${projectId}/tree`), enabled: !!value })
  const [f, setF] = useState<any>({})
  useEffect(() => { if (value) setF({ code: value.code || '', name: value.name || '', description: value.description || '', domain_id: value.domain_id || null, lead_org_unit_id: value.lead_org?.id || null, contributor_org_ids: (value.contributors || []).map((c: any) => c.id), item_id: value.item_id || null, owner_id: value.owner?.id || null, start_date: value.start_date || null, end_date: value.end_date || null, status: value.status || 'ACTIVE' }) }, [value])
  const set = (k: string) => (v: any) => setF((x: any) => ({ ...x, [k]: v }))
  const isNew = value && !value.id
  const save = useAction(() => (isNew ? api.post(`/plans/${planId}/work-packages`, f) : api.put(`/work-packages/${value.id}`, f, { version: value.version })), { success: 'Work package saved', invalidate: refresh, onDone: onClose })
  const del = useAction(() => api.del(`/work-packages/${value.id}`), { success: 'Work package removed', invalidate: refresh, onDone: onClose })
  const orgData = (orgs.data || []).map((o: any) => ({ value: o.id, label: `${o.code} — ${o.name}` }))
  return (
    <Modal opened={!!value} onClose={onClose} size="lg" title={isNew ? 'New work package' : 'Edit work package'}>
      <Stack>
        <Group grow><TextInput label="Code" required value={f.code || ''} onChange={(e) => set('code')(e.currentTarget.value)} /><Select label="Status" allowDeselect={false} value={f.status} onChange={set('status')} data={[{ value: 'ACTIVE', label: 'Active' }, { value: 'ON_HOLD', label: 'On hold' }, { value: 'CLOSED', label: 'Closed' }]} /></Group>
        <TextInput label="Name" required value={f.name || ''} onChange={(e) => set('name')(e.currentTarget.value)} />
        <Group grow>
          <Select label="Lead directorate" clearable searchable value={f.lead_org_unit_id} onChange={set('lead_org_unit_id')} data={orgData} />
          <Select label="Process domain" clearable value={f.domain_id} onChange={set('domain_id')} data={(domains.data || []).map((d: any) => ({ value: d.id, label: d.name }))} />
        </Group>
        <MultiSelect label="Contributing directorates" searchable value={f.contributor_org_ids || []} onChange={set('contributor_org_ids')} data={orgData} />
        <Select label="Engineering item" clearable searchable value={f.item_id} onChange={set('item_id')} data={(tree.data?.items || []).map((i: any) => ({ value: i.id, label: `${i.code} — ${i.name}` }))} />
        <UserSelect label="Owner" value={f.owner_id} onChange={set('owner_id')} />
        <Group grow><DateInput label="Start" clearable value={toDate(f.start_date)} onChange={(d) => set('start_date')(iso(d))} /><DateInput label="End" clearable value={toDate(f.end_date)} onChange={(d) => set('end_date')(iso(d))} /></Group>
        <Group justify="space-between">
          <div>{!isNew && <Button variant="subtle" color="red" loading={del.isPending} onClick={() => del.mutate(undefined)}>Remove</Button>}</div>
          <Group><Button variant="default" onClick={onClose}>Cancel</Button><Button disabled={!f.code || (f.name || '').length < 2} loading={save.isPending} onClick={() => save.mutate(undefined)}>Save</Button></Group>
        </Group>
      </Stack>
    </Modal>
  )
}

function ActivityModal({ value, plan, planId, refresh, onClose }: { value: any | null; plan: any; planId: string; refresh: any[][]; onClose: () => void }) {
  const [f, setF] = useState<any>({})
  useEffect(() => { if (value) setF({ title: value.title || '', description: value.description || '', work_package_id: value.work_package_id || null, phase_id: value.phase_id || null, owner_id: value.owner?.id || null, start_date: value.start_date || null, end_date: value.end_date || null, estimated_hours: value.estimated_hours || 0, priority: value.priority || 'MEDIUM', weight: value.weight ?? null, status: value.status || 'NOT_STARTED' }) }, [value])
  const set = (k: string) => (v: any) => setF((x: any) => ({ ...x, [k]: v }))
  const isNew = value && !value.id
  const save = useAction(() => (isNew ? api.post(`/plans/${planId}/activities`, f) : api.put(`/activities/${value.id}`, f, { version: value.version })), { success: 'Activity saved', invalidate: refresh, onDone: onClose })
  const del = useAction(() => api.del(`/activities/${value.id}`), { success: 'Activity removed', invalidate: refresh, onDone: onClose })
  return (
    <Modal opened={!!value} onClose={onClose} size="lg" title={isNew ? 'New activity' : 'Edit activity'}>
      <Stack>
        <TextInput label="Title" required value={f.title || ''} onChange={(e) => set('title')(e.currentTarget.value)} />
        <Group grow>
          <Select label="Work package" clearable value={f.work_package_id} onChange={set('work_package_id')} data={plan.work_packages.map((w: any) => ({ value: w.id, label: `${w.code} — ${w.name}` }))} />
          <Select label="Phase" clearable value={f.phase_id} onChange={set('phase_id')} data={plan.phases.map((p: any) => ({ value: p.id, label: p.name }))} />
        </Group>
        <UserSelect label="Owner" value={f.owner_id} onChange={set('owner_id')} />
        <Group grow><DateInput label="Start" clearable value={toDate(f.start_date)} onChange={(d) => set('start_date')(iso(d))} /><DateInput label="End" clearable value={toDate(f.end_date)} onChange={(d) => set('end_date')(iso(d))} /></Group>
        <Group grow>
          <NumberInput label="Estimated hours" min={0} value={f.estimated_hours ?? 0} onChange={(v) => set('estimated_hours')(Number(v) || 0)} />
          <Select label="Priority" allowDeselect={false} value={f.priority} onChange={set('priority')} data={Object.keys(PRIORITY_COLOR)} />
          <Select label="Status" allowDeselect={false} value={f.status} onChange={set('status')} data={ACTIVITY_STATES} />
        </Group>
        <Group justify="space-between">
          <div>{!isNew && <Button variant="subtle" color="red" loading={del.isPending} onClick={() => del.mutate(undefined)}>Remove</Button>}</div>
          <Group><Button variant="default" onClick={onClose}>Cancel</Button><Button disabled={(f.title || '').length < 2} loading={save.isPending} onClick={() => save.mutate(undefined)}>Save</Button></Group>
        </Group>
      </Stack>
    </Modal>
  )
}

function ImportModal({ opened, planId, refresh, onClose }: { opened: boolean; planId: string; refresh: any[][]; onClose: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [result, setResult] = useState<any | null>(null)
  const send = (dry: boolean) => { const fd = new FormData(); fd.append('file', file as File); return api.post(`/plans/${planId}/import`, fd, { dry_run: dry }) }
  const check = useAction(() => send(true), { onDone: setResult })
  const commit = useAction(() => send(false), { success: (r: any) => `${r.created} task(s) imported`, invalidate: refresh, onDone: () => { setFile(null); setResult(null); onClose() } })
  return (
    <Modal opened={opened} onClose={onClose} size="lg" title="Import tasks from CSV">
      <Stack>
        <Text size="sm" c="dimmed">Adds new tasks to this plan. Needs a <Code>title</Code> column; these are optional: <Code>kind</Code> <Code>priority</Code> <Code>activity</Code> <Code>work_package</Code> <Code>assignee</Code> <Code>start_date</Code> <Code>due_date</Code> <Code>estimated_hours</Code>. Dates are YYYY-MM-DD.</Text>
        <FileInput label="CSV file" accept=".csv,text/csv" value={file} onChange={(f) => { setFile(f); setResult(null) }} leftSection={<IconUpload size={15} />} clearable />
        {result && !result.errors.length && <Alert color="teal" p="xs">All {result.valid_rows} row(s) are valid and ready to import.</Alert>}
        {result && !!result.errors.length && (
          <Alert color="red" p="xs" title={`${result.errors.length} row(s) have problems. Nothing will be imported until they are fixed.`}>
            <Stack gap={2}>{result.errors.slice(0, 30).map((e: any) => <Text key={e.row} size="xs">Row {e.row}: {e.errors.join(' ')}</Text>)}</Stack>
          </Alert>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Cancel</Button>
          <Button variant="light" disabled={!file} loading={check.isPending} onClick={() => check.mutate(undefined)}>Check file</Button>
          <Button disabled={!result || !!result.errors.length || !result.valid_rows} loading={commit.isPending} onClick={() => commit.mutate(undefined)}>Import {result?.valid_rows || ''} task(s)</Button>
        </Group>
      </Stack>
    </Modal>
  )
}
