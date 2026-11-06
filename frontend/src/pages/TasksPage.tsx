import { Badge, Button, Group, Modal, Progress, SegmentedControl, Select, Stack, Text, Textarea } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconCalendar, IconLayoutKanban, IconPlus } from '@tabler/icons-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, errorText } from '../api/client'
import { useProjects } from '../api/hooks'
import { PageTitle, UserAvatar } from '../components/common'
import TaskDrawer, { KIND_LABEL, PRIORITY_COLOR, type TaskTarget } from '../components/TaskDrawer'

export default function TasksPage() {
  const [sp, setSp] = useSearchParams()
  const qc = useQueryClient()
  const [scope, setScope] = useState('mine')
  const [project, setProject] = useState<string | null>(sp.get('project'))
  // Development tasks follow their own lifecycle (code review, merged, testing), so they get their own board.
  const [board, setBoard] = useState<string>(sp.get('board') === 'dev' ? 'dev' : 'work')
  const projects = useProjects()
  const all = useQuery<any[]>({ queryKey: ['work-items', scope, project], queryFn: () => api.get('/work-items', { mine: scope === 'mine' && !project, project_id: project }) })
  const data = useMemo(() => (all.data || []).filter((w) => (board === 'dev') === (w.kind === 'DEVELOPMENT')), [all.data, board])
  const life = useQuery<any>({ queryKey: ['task-lifecycle', project, board], queryFn: () => api.get('/task-lifecycle', { project_id: project, kind: board === 'dev' ? 'DEVELOPMENT' : undefined }), staleTime: 300_000 })
  const [over, setOver] = useState<string | null>(null)
  const [target, setTarget] = useState<TaskTarget | null>(null)
  const [reasonFor, setReasonFor] = useState<{ task: any; rule: any } | null>(null)
  const [reason, setReason] = useState('')

  useEffect(() => { const o = sp.get('open'); if (o) setTarget({ id: o }) }, [sp])

  const states: any[] = life.data?.states || []
  const transitions: any[] = life.data?.transitions || []
  const columns = useMemo(() => states.filter((s) => s.category !== 'CANCELLED'), [states])

  const send = async (w: any, to: string, comment?: string) => {
    try {
      await api.post(`/work-items/${w.id}/transition`, { to, comment }, { version: w.version })
    } catch (e) { notifications.show({ color: 'red', title: `${w.key} did not move`, message: errorText(e), autoClose: 9000 }) }
    qc.invalidateQueries({ queryKey: ['work-items'] })
    qc.invalidateQueries({ queryKey: ['work-item', w.id] })
  }

  const drop = (w: any, to: string) => {
    if (w.status === to) return
    const rule = transitions.find((t) => t.from === w.status && t.to === to)
    if (!rule) {
      const allowed = transitions.filter((t) => t.from === w.status).map((t) => states.find((s) => s.code === t.to)?.label).filter(Boolean).join(', ')
      notifications.show({ color: 'orange', title: `${w.key} cannot move there`, message: allowed ? `From here it can go to: ${allowed}.` : 'This status is final.' })
      return
    }
    if (rule.reason) { setReasonFor({ task: w, rule }); setReason(''); return }
    send(w, to)
  }

  const closeDrawer = () => { setTarget(null); if (sp.get('open')) { sp.delete('open'); setSp(sp, { replace: true }) } }
  const cancelled = data.filter((w) => states.find((s) => s.code === w.status)?.category === 'CANCELLED').length

  return (
    <div className="page" style={{ maxWidth: 1900 }}>
      <PageTitle icon={<IconLayoutKanban size={22} />} title="Tasks board" sub="Drag a card to change its status. Only allowed moves go through, and completion gates are checked on the server."
        extra={<>
          <Select placeholder="All projects" clearable searchable w={170} value={project} onChange={setProject} data={(projects.data || []).map((p) => ({ value: p.id, label: p.code }))} />
          <SegmentedControl value={board} onChange={setBoard} data={[{ label: 'Work tasks', value: 'work' }, { label: 'Development', value: 'dev' }]} />
          {!project && <SegmentedControl value={scope} onChange={setScope} data={[{ label: 'Mine', value: 'mine' }, { label: 'My scope', value: 'scope' }]} />}
          <Button leftSection={<IconPlus size={16} />} onClick={() => setTarget({ defaults: { ...(project ? { project_id: project } : {}), ...(board === 'dev' ? { kind: 'DEVELOPMENT' } : {}) } })}>New task</Button>
        </>} />
      <div className="kanban" style={{ gridTemplateColumns: `repeat(${columns.length || 1}, minmax(250px, 1fr))` }}>
        {columns.map((c) => {
          const items = data.filter((w) => w.status === c.code)
          return (
            <div key={c.code} className={`kanban-col ${over === c.code ? 'over' : ''}`} onDragOver={(e) => { e.preventDefault(); setOver(c.code) }} onDragLeave={() => setOver(null)}
              onDrop={(e) => { setOver(null); const w = data.find((x) => x.id === e.dataTransfer.getData('id')); if (w) drop(w, c.code) }}>
              <Group justify="space-between" px={4} mb={8}><Group gap={6}><span style={{ width: 8, height: 8, borderRadius: 4, background: `var(--mantine-color-${c.color || 'gray'}-6)` }} /><Text fw={650} size="sm">{c.label}</Text></Group><Badge color={c.color} size="sm">{items.length}</Badge></Group>
              {items.map((w) => {
                const done = c.category === 'DONE'
                const late = w.due_date && !done && dayjs(w.due_date).isBefore(dayjs(), 'day')
                return (
                  <div key={w.id} className="kanban-card" draggable onDragStart={(e) => e.dataTransfer.setData('id', w.id)} onClick={() => setTarget({ id: w.id })}>
                    <Group justify="space-between" gap={4}><Text size="xs" c="dimmed" fw={600}>{w.key}</Text><Badge size="xs" color={PRIORITY_COLOR[w.priority]}>{w.priority}</Badge></Group>
                    <Text size="sm" fw={550} mt={4} lineClamp={2}>{w.title}</Text>
                    <Group gap={4} mt={6}>
                      {w.kind !== 'TASK' && <Badge size="xs" variant="outline" color="grape">{KIND_LABEL[w.kind]}</Badge>}
                      {w.work_package && <Badge size="xs" color="indigo" variant="light">{w.work_package.code}</Badge>}
                      {w.item && <Badge size="xs" color="violet">{w.item.code}</Badge>}
                      {w.document && <Badge size="xs" color="gray">{w.document.number}</Badge>}
                    </Group>
                    {c.category === 'ACTIVE' && <Progress value={w.progress} size="xs" mt={8} />}
                    <Group justify="space-between" mt={8}>
                      <Text size="xs" c={late ? 'red' : 'dimmed'} fw={late ? 600 : 400}>{w.due_date ? <><IconCalendar size={11} /> {dayjs(w.due_date).format('DD MMM YYYY')}{late ? ' · late' : ''}</> : ''}</Text>
                      <UserAvatar user={w.assignee} size={22} />
                    </Group>
                  </div>
                )
              })}
            </div>
          )
        })}
      </div>
      {!!cancelled && <Text size="xs" c="dimmed" mt="sm">{cancelled} cancelled task(s) are not shown on the board.</Text>}
      <TaskDrawer target={target} onClose={closeDrawer} />
      <Modal opened={!!reasonFor} onClose={() => setReasonFor(null)} title={`${reasonFor?.rule?.label || 'Change status'}: ${reasonFor?.task?.key || ''}`}>
        <Stack>
          <Textarea label="Reason" required autosize minRows={3} autoFocus value={reason} onChange={(e) => setReason(e.currentTarget.value)} />
          <Group justify="flex-end"><Button variant="default" onClick={() => setReasonFor(null)}>Cancel</Button><Button disabled={!reason.trim()} onClick={() => { const r = reasonFor!; setReasonFor(null); send(r.task, r.rule.to, reason) }}>Confirm</Button></Group>
        </Stack>
      </Modal>
    </div>
  )
}
