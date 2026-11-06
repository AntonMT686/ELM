import { Alert, Badge, Button, Card, Checkbox, Grid, Group, Kbd, Modal, PasswordInput, ScrollArea, SegmentedControl, Select, Stack, Table, Tabs, Text, Textarea, TextInput, Title } from '@mantine/core'
import { DateTimePicker } from '@mantine/dates'
import { useDebouncedValue } from '@mantine/hooks'
import { modals } from '@mantine/modals'
import { IconArrowBackUp, IconCheck, IconExternalLink, IconInbox, IconRosetteDiscountCheck, IconSwitchHorizontal, IconUserShare, IconX } from '@tabler/icons-react'
import dayjs from 'dayjs'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ChecklistAnswerForm, checklistNotOk, checklistReady, type Answer } from '../components/ReviewChecklist'
import { api } from '../api/client'
import { useAction, useDocWorkflow, useInbox, useUsers } from '../api/hooks'
import type { InboxTask } from '../api/types'
import { ClassTag, EmptyBlock, Hash, PageTitle, StatusTag, TypeBadge, UserAvatar, When } from '../components/common'
import DocumentPreview from '../components/DocumentPreview'
import LifecycleTracker, { MiniStages } from '../components/LifecycleTracker'

function group(tasks: InboxTask[]) {
  const soon = dayjs().add(2, 'day')
  return {
    overdue: tasks.filter((t) => t.overdue),
    soon: tasks.filter((t) => !t.overdue && t.due_at && dayjs(t.due_at).isBefore(soon)),
    later: tasks.filter((t) => !t.overdue && (!t.due_at || !dayjs(t.due_at).isBefore(soon))),
  }
}

export default function InboxPage() {
  const [sp, setSp] = useSearchParams()
  const { data, isLoading } = useInbox()
  const [tab, setTab] = useState<string | null>(sp.get('tab') || 'pending')
  const [filter, setFilter] = useState('all')
  const pending = useMemo(() => (data?.pending || []).filter((t) => filter === 'all' || (filter === 'sign' ? t.stage.type === 'signature' : t.stage.type !== 'signature')), [data, filter])
  const [selId, setSelId] = useState<string | undefined>(sp.get('task') || undefined)
  const sel = pending.find((t) => t.id === selId) || pending.find((t) => t.document.id === sp.get('doc')) || pending[0]

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.closest('input,textarea,[contenteditable]')) return
      const i = pending.findIndex((t) => t.id === sel?.id)
      if (e.key === 'j' && i < pending.length - 1) setSelId(pending[i + 1].id)
      if (e.key === 'k' && i > 0) setSelId(pending[i - 1].id)
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [pending, sel])

  const g = group(pending)
  const item = (t: InboxTask) => (
    <div key={t.id} className={`inbox-item ${sel?.id === t.id ? 'active' : ''}`} onClick={() => { setSelId(t.id); setSp({ task: t.id }, { replace: true }) }}>
      <Group justify="space-between" wrap="nowrap" gap={8}>
        <Group gap={6} wrap="nowrap"><TypeBadge type={t.document.type} /><Text size="sm" fw={650}>{t.document.number}</Text></Group>
        <Text size="xs" c={t.overdue ? 'red' : 'dimmed'} style={{ whiteSpace: 'nowrap' }}>{t.due_at ? dayjs(t.due_at).fromNow() : ''}</Text>
      </Group>
      <Text size="sm" truncate my={4}>{t.document.title}</Text>
      <Group justify="space-between">
        <Badge size="sm" color={t.stage.type === 'signature' ? 'yellow' : t.stage.type === 'approval' ? 'grape' : 'blue'} leftSection={t.stage.type === 'signature' ? <IconRosetteDiscountCheck size={11} /> : undefined}>{t.stage.name}</Badge>
        <MiniStages stages={t.stages} index={t.stage.index} />
      </Group>
      {t.delegated_from && <Text size="xs" c="dimmed" mt={4}><IconUserShare size={12} /> on behalf of {t.delegated_from.full_name}</Text>}
    </div>
  )
  const section = (title: string, list: InboxTask[], color?: string) => list.length ? (
    <div style={{ marginBottom: 10 }}>
      <Text size="xs" fw={700} tt="uppercase" c={color || 'dimmed'} px={8} py={6} style={{ letterSpacing: '.06em' }}>{title} · {list.length}</Text>
      {list.map(item)}
    </div>
  ) : null

  return (
    <div className="page" style={{ maxWidth: 1800 }}>
      <PageTitle icon={<IconInbox size={22} />} title="Action inbox" sub="Everything that needs your review, approval or signature — bound to the exact revision you see." />
      <Tabs value={tab} onChange={setTab} mb="md">
        <Tabs.List>
          <Tabs.Tab value="pending" rightSection={<Badge size="sm" variant="filled" circle>{data?.pending.length || 0}</Badge>}>Waiting for me</Tabs.Tab>
          <Tabs.Tab value="submitted">Submitted by me ({data?.submitted.length || 0})</Tabs.Tab>
          <Tabs.Tab value="completed">Recently completed</Tabs.Tab>
          <Tabs.Tab value="delegation">Out-of-office delegation</Tabs.Tab>
        </Tabs.List>
      </Tabs>
      {tab === 'pending' && (
        <Grid gutter="md">
          <Grid.Col span={{ base: 12, lg: 4, xl: 3.5 }}>
            <Card p={8} style={{ position: 'sticky', top: 76 }}>
              <SegmentedControl fullWidth size="xs" value={filter} onChange={setFilter} data={[{ label: 'All', value: 'all' }, { label: 'Reviews', value: 'review' }, { label: 'Signatures', value: 'sign' }]} mb={8} />
              <ScrollArea.Autosize mah="calc(100vh - 260px)">
                {isLoading ? <Text c="dimmed" p="lg">Loading…</Text> : pending.length === 0 ? <EmptyBlock text="Nothing waiting on you. Great work!" /> : <>{section('Overdue', g.overdue, 'red')}{section('Due within 2 days', g.soon, 'orange')}{section('Upcoming', g.later)}</>}
              </ScrollArea.Autosize>
              <Text size="xs" c="dimmed" p={8}>Tip: press <Kbd size="xs">j</Kbd> / <Kbd size="xs">k</Kbd> to move between items.</Text>
            </Card>
          </Grid.Col>
          <Grid.Col span={{ base: 12, lg: 8, xl: 8.5 }}>{sel ? <TaskDetail key={sel.id} task={sel} /> : <Card><EmptyBlock text="Select an item" /></Card>}</Grid.Col>
        </Grid>
      )}
      {tab === 'submitted' && <Submitted rows={data?.submitted || []} />}
      {tab === 'completed' && <Completed rows={data?.completed || []} />}
      {tab === 'delegation' && <Delegation />}
    </div>
  )
}

function TaskDetail({ task }: { task: InboxTask }) {
  const nav = useNavigate()
  const wf = useDocWorkflow(task.document.id)
  const run = wf.data?.find((r) => r.status === 'ACTIVE') || wf.data?.[0]
  const [comment, setComment] = useState('')
  const [checks, setChecks] = useState<Record<string, boolean>>({})
  const [signOpen, setSignOpen] = useState(false)
  const [reassignOpen, setReassignOpen] = useState(false)
  const [pendingDecision, setPendingDecision] = useState('')
  const [answers, setAnswers] = useState<Record<string, Answer>>({})
  const prep = (task as any).doc_checklist || { items: [], earlier: [] }
  const notOk = checklistNotOk(prep.items, answers)
  const allChecked = task.stage.checklist.every((c) => checks[c]) && checklistReady(prep.items, answers)
  const decide = useAction((d: string) => { setPendingDecision(d); return api.post(`/tasks/${task.id}/decide`, { decision: d, comment: comment || undefined, checklist: checks, item_results: answers }) }, {
    success: (r: any) => (r.instance_status === 'ACTIVE' ? 'Decision recorded — moved to the next stage' : r.instance_status === 'COMPLETED' ? 'Approved — document is ready for release' : 'Returned to the author with your comments'),
    invalidate: [['inbox'], ['doc', task.document.id], ['doc-wf', task.document.id], ['dashboard']],
  })
  const isSign = task.stage.type === 'signature'

  return (
    <Stack gap="md">
      <Card p="lg">
        <Group justify="space-between" align="flex-start" wrap="wrap">
          <div style={{ minWidth: 0 }}>
            <Group gap={8}><TypeBadge type={task.document.type} /><Text fw={700} size="lg">{task.document.number}</Text><Badge color="gray">Rev {task.revision.label}.{task.revision.iteration}</Badge><ClassTag value={task.document.classification} />{task.cycle_no > 1 && <Badge color="orange">Review cycle {task.cycle_no}</Badge>}</Group>
            <Title order={4} mt={4}>{task.document.title}</Title>
            <Group gap={14} mt={6}>
              <Text size="xs" c="dimmed">Submitted by <b>{task.initiator.full_name}</b> <When at={task.submitted_at} /></Text>
              {task.document.item && <Text size="xs" c="dimmed">{task.document.item.level_name}: <b>{task.document.item.code}</b></Text>}
              {task.document.project && <Text size="xs" c="dimmed">Project <b>{task.document.project.code}</b></Text>}
              <Text size="xs" c="dimmed" component="div">SHA-256 <Hash value={task.revision.sha256} /></Text>
            </Group>
          </div>
          <Group>
            <Button variant="default" leftSection={<IconExternalLink size={16} />} onClick={() => nav(`/documents/${task.document.id}`)}>Open document</Button>
            <Button variant="default" leftSection={<IconSwitchHorizontal size={16} />} onClick={() => setReassignOpen(true)}>Reassign</Button>
          </Group>
        </Group>
        {run && <div style={{ marginTop: 14 }}><LifecycleTracker run={run} /></div>}
      </Card>

      <Grid gutter="md">
        <Grid.Col span={{ base: 12, xl: 7.5 }}>
          <Card p={10}><Text fw={600} size="sm" px={6} pb={8}>Content under review</Text><DocumentPreview docId={task.document.id} revisionId={task.revision.id} ext={task.revision.ext} height={620} /></Card>
        </Grid.Col>
        <Grid.Col span={{ base: 12, xl: 4.5 }}>
          <Card style={{ position: 'sticky', top: 76 }}>
            <Group gap={8} mb="sm">{isSign ? <IconRosetteDiscountCheck color="#d97706" /> : <IconCheck color="#2563eb" />}<Title order={5}>Your action: {task.stage.name}</Title></Group>
            {task.stage.instructions && <Alert variant="light" mb="sm">{task.stage.instructions}</Alert>}
            {task.overdue && <Alert color="red" variant="light" mb="sm">This action is overdue.</Alert>}
            {isSign ? (
              <>
                <Text size="sm" mb="md">You are signing revision <b>{task.revision.label}</b>. The signature is applied cryptographically over SHA-256 <Hash value={task.revision.sha256} /> — any later change invalidates it.</Text>
                <Button fullWidth size="md" color="yellow" leftSection={<IconRosetteDiscountCheck size={18} />} onClick={() => setSignOpen(true)}>Sign digitally</Button>
              </>
            ) : (
              <>
                <ChecklistAnswerForm items={prep.items} answers={answers} onChange={setAnswers} earlier={prep.earlier} />
                {task.stage.checklist.length > 0 && (
                  <Stack gap={8} mb="md">
                    <Text fw={600} size="sm">Process checklist (set by the process owner)</Text>
                    {task.stage.checklist.map((c) => <Checkbox key={c} label={c} checked={!!checks[c]} onChange={(e) => setChecks({ ...checks, [c]: e.currentTarget.checked })} />)}
                  </Stack>
                )}
                <Textarea autosize minRows={4} value={comment} onChange={(e) => setComment(e.currentTarget.value)} placeholder="Comments (required when returning or rejecting)…" maxLength={5000} />
                <Stack gap={8} mt="md">
                  <Button size="md" fullWidth leftSection={<IconCheck size={18} />} disabled={!allChecked} loading={decide.isPending && pendingDecision === 'approve'} onClick={() => decide.mutate('approve')}>
                    {task.stage.type === 'approval' ? 'Approve' : 'Accept & forward'}
                  </Button>
                  {!allChecked && (task.stage.checklist.length > 0 || prep.items.length > 0) && <Text size="xs" c="dimmed" ta="center">{notOk.length ? `${notOk.length} item(s) are Not OK: request changes instead.` : 'Answer every checklist item (remarks for Not OK / N/A) to enable approval.'}</Text>}
                  <Group grow>
                    <Button variant="default" leftSection={<IconArrowBackUp size={16} />} disabled={!comment.trim() || prep.items.some((i: any) => answers[i.id]?.result && answers[i.id].result !== 'OK' && !(answers[i.id].remark || '').trim())} loading={decide.isPending && pendingDecision === 'request_changes'} onClick={() => decide.mutate('request_changes')}>Request changes</Button>
                    {task.stage.allow_reject && (
                      <Button variant="light" color="red" leftSection={<IconX size={16} />} disabled={!comment.trim()}
                        onClick={() => modals.openConfirmModal({ title: 'Reject this submission?', children: <Text size="sm">The review cycle ends and the author is notified.</Text>, labels: { confirm: 'Reject', cancel: 'Cancel' }, confirmProps: { color: 'red' }, onConfirm: () => decide.mutate('reject') })}>Reject</Button>
                    )}
                  </Group>
                </Stack>
              </>
            )}
            <Text size="xs" c="dimmed" mt="md">Stage {task.stage.index + 1} of {task.stage.count} · {task.due_at ? `due ${dayjs(task.due_at).format('DD MMM YYYY, HH:mm')}` : 'no SLA'}</Text>
          </Card>
        </Grid.Col>
      </Grid>
      <SignModal opened={signOpen} onClose={() => setSignOpen(false)} task={task} />
      <ReassignModal opened={reassignOpen} onClose={() => setReassignOpen(false)} task={task} />
    </Stack>
  )
}

function SignModal({ opened, onClose, task }: { opened: boolean; onClose: () => void; task: InboxTask }) {
  const [password, setPassword] = useState('')
  const [remark, setRemark] = useState('')
  const sign = useAction(() => api.post(`/tasks/${task.id}/sign`, { password, comment: remark || undefined }), { success: 'Signature applied and recorded', invalidate: [['inbox'], ['doc', task.document.id], ['doc-wf', task.document.id]], onDone: onClose })
  return (
    <Modal opened={opened} onClose={onClose} title={<Group gap={8}><IconRosetteDiscountCheck color="#d97706" /><Text fw={650}>Confirm digital signature</Text></Group>}>
      <Alert color="yellow" variant="light" mb="md" title="Signing is a legally significant action.">
        Document <b>{task.document.number}</b> rev <b>{task.revision.label}</b><br /><span className="hash">SHA-256 {task.revision.sha256}</span>
      </Alert>
      <form onSubmit={(e) => { e.preventDefault(); sign.mutate(undefined) }}>
        <Stack>
          <PasswordInput data-autofocus required label="Re-enter your password to confirm intent" value={password} onChange={(e) => setPassword(e.currentTarget.value)} />
          <TextInput label="Remark (optional)" value={remark} onChange={(e) => setRemark(e.currentTarget.value)} />
          <Group justify="flex-end"><Button variant="default" onClick={onClose}>Cancel</Button><Button type="submit" color="yellow" loading={sign.isPending} disabled={!password}>Sign</Button></Group>
        </Stack>
      </form>
    </Modal>
  )
}

export function UserSelect({ value, onChange, label, placeholder, required }: { value: string | null; onChange: (v: string | null) => void; label?: string; placeholder?: string; required?: boolean }) {
  const [q, setQ] = useState('')
  const [deb] = useDebouncedValue(q, 200)
  const users = useUsers(deb)
  return (
    <Select searchable required={required} label={label} placeholder={placeholder || 'Search people'} value={value} onChange={onChange} onSearchChange={setQ} filter={({ options }) => options}
      data={(users.data || []).map((u: any) => ({ value: u.id, label: `${u.full_name}${u.designation ? ' — ' + u.designation : ''}` }))} nothingFoundMessage="No one found" />
  )
}

function ReassignModal({ opened, onClose, task }: { opened: boolean; onClose: () => void; task: InboxTask }) {
  const [userId, setUserId] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const act = useAction(() => api.post(`/tasks/${task.id}/reassign`, { user_id: userId, reason }), { success: 'Task reassigned', invalidate: [['inbox']], onDone: onClose })
  return (
    <Modal opened={opened} onClose={onClose} title="Reassign this task">
      <Stack>
        <UserSelect label="New assignee" required value={userId} onChange={setUserId} />
        <Text size="xs" c="dimmed">Must hold the role required for this stage; separation-of-duties rules still apply.</Text>
        <TextInput label="Reason" required value={reason} onChange={(e) => setReason(e.currentTarget.value)} />
        <Group justify="flex-end"><Button variant="default" onClick={onClose}>Cancel</Button><Button disabled={!userId || reason.length < 3} loading={act.isPending} onClick={() => act.mutate(undefined)}>Reassign</Button></Group>
      </Stack>
    </Modal>
  )
}

function Submitted({ rows }: { rows: any[] }) {
  const nav = useNavigate()
  if (!rows.length) return <Card><EmptyBlock text="No active submissions" /></Card>
  return (
    <Card p={0}>
      <Table>
        <Table.Thead><Table.Tr><Table.Th>Document</Table.Th><Table.Th>Status</Table.Th><Table.Th>Current stage</Table.Th><Table.Th>Submitted</Table.Th></Table.Tr></Table.Thead>
        <Table.Tbody>
          {rows.map((r) => (
            <Table.Tr key={r.instance_id} className="clickable" onClick={() => nav(`/documents/${r.document.id}`)}>
              <Table.Td><Group gap={8}><TypeBadge type={r.document.type} /><Text fw={600} size="sm">{r.document.number}</Text><Text size="sm" c="dimmed" truncate maw={380}>{r.document.title}</Text></Group></Table.Td>
              <Table.Td><StatusTag status={r.document.status} /></Table.Td>
              <Table.Td><Badge color="gray">{r.current_stage_key}</Badge></Table.Td>
              <Table.Td><When at={r.started_at} /></Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Card>
  )
}

function Completed({ rows }: { rows: InboxTask[] }) {
  const nav = useNavigate()
  if (!rows.length) return <Card><EmptyBlock text="No recent decisions" /></Card>
  return (
    <Card>
      <Stack gap={2}>
        {rows.map((t) => (
          <div key={t.id} className="inbox-item" onClick={() => nav(`/documents/${t.document.id}`)}>
            <Group justify="space-between" wrap="nowrap">
              <Group gap={10} wrap="nowrap"><StatusTag status={t.status} /><TypeBadge type={t.document.type} /><Text size="sm" fw={600}>{t.document.number}</Text><Text size="sm" c="dimmed">· {t.stage.name}</Text></Group>
              <Text size="xs" c="dimmed"><When at={t.acted_at} /></Text>
            </Group>
            <Text size="sm" mt={4}>{t.document.title}</Text>
            {t.comment && <Text size="xs" c="dimmed" mt={2}>“{t.comment}”</Text>}
          </div>
        ))}
      </Stack>
    </Card>
  )
}

function Delegation() {
  const [toUser, setToUser] = useState<string | null>(null)
  const [from, setFrom] = useState<Date | null>(new Date())
  const [to, setTo] = useState<Date | null>(null)
  const [reason, setReason] = useState('')
  const [rows, setRows] = useState<any[]>([])
  const load = () => api.get('/delegations').then(setRows)
  useEffect(() => { load() }, [])
  const act = useAction(() => api.post('/delegations', { to_user_id: toUser, valid_from: from?.toISOString(), valid_to: to?.toISOString(), reason }), { success: 'Delegation saved', onDone: () => { setToUser(null); setReason(''); load() } })
  return (
    <Grid>
      <Grid.Col span={{ base: 12, lg: 4.5 }}>
        <Card>
          <Title order={5}>Delegate my review / approval tasks</Title>
          <Text size="sm" c="dimmed" my="sm">While you are away, the delegate can act on your workflow tasks. Decisions record both identities. Signatures can never be delegated.</Text>
          <Stack>
            <UserSelect label="Delegate" required value={toUser} onChange={setToUser} />
            <Group grow><DateTimePicker label="From" value={from} onChange={setFrom} required /><DateTimePicker label="Until" value={to} onChange={setTo} required minDate={from || undefined} /></Group>
            <TextInput label="Reason" placeholder="e.g. Official tour" value={reason} onChange={(e) => setReason(e.currentTarget.value)} required />
            <Button disabled={!toUser || !from || !to || reason.length < 3} loading={act.isPending} onClick={() => act.mutate(undefined)}>Save delegation</Button>
          </Stack>
        </Card>
      </Grid.Col>
      <Grid.Col span={{ base: 12, lg: 7.5 }}>
        <Card p={0}>
          <Table>
            <Table.Thead><Table.Tr><Table.Th>From</Table.Th><Table.Th>To</Table.Th><Table.Th>Period</Table.Th><Table.Th>Reason</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>
              {rows.map((r) => (
                <Table.Tr key={r.id}><Table.Td><UserAvatar user={r.from} showName /></Table.Td><Table.Td><UserAvatar user={r.to} showName /></Table.Td>
                  <Table.Td>{dayjs(r.valid_from).format('DD MMM')} → {dayjs(r.valid_to).format('DD MMM YYYY')}</Table.Td><Table.Td>{r.reason}</Table.Td></Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
          {!rows.length && <EmptyBlock text="No delegations" />}
        </Card>
      </Grid.Col>
    </Grid>
  )
}
