import { Avatar, Group, Text, Tooltip } from '@mantine/core'
import { IconCheck, IconLoader2, IconRosetteDiscountCheck, IconX } from '@tabler/icons-react'
import dayjs from 'dayjs'
import type { WorkflowRun } from '../api/types'
import { UserAvatar } from './common'

const cls = (s: string) => ({ DONE: 'done', ACTIVE: 'active', RETURNED: 'returned', REJECTED: 'returned', SKIPPED: 'skipped' } as Record<string, string>)[s] || ''
const ring = (s: string) => (s === 'APPROVED' || s === 'SIGNED' ? '0 0 0 2px #22c55e' : s === 'PENDING' ? '0 0 0 2px #60a5fa' : s === 'CHANGES_REQUESTED' || s === 'REJECTED' ? '0 0 0 2px #ef4444' : undefined)

/** Horizontal, glanceable stage tracker: who acts, what they decided, what is next. */
export default function LifecycleTracker({ run, compact = false }: { run: WorkflowRun; compact?: boolean }) {
  return (
    <div className="track">
      {run.stages.map((s) => {
        const people = s.tasks.filter((t) => t.status !== 'CANCELLED' && t.status !== 'REASSIGNED')
        const icon = s.status === 'DONE' ? <IconCheck size={16} color="#16a34a" /> : s.status === 'ACTIVE' ? <IconLoader2 size={16} color="#2563eb" />
          : s.status === 'RETURNED' || s.status === 'REJECTED' ? <IconX size={16} color="#dc2626" /> : null
        return (
          <div key={s.key} className={`track-stage ${cls(s.status)}`}>
            <Group justify="space-between" wrap="nowrap">
              <div className="t-type">{s.type === 'signature' ? <Group gap={3}><IconRosetteDiscountCheck size={12} />signature</Group> : s.type}</div>
              {icon}
            </Group>
            <div className="t-name">{s.name}</div>
            {!compact && (
              <Avatar.Group spacing={6} mt={8} style={{ minHeight: 28 }}>
                {people.slice(0, 4).map((t) => (
                  <Tooltip key={t.id} multiline w={240} label={<div><b>{t.assignee.full_name}</b><br />{t.status.replace('_', ' ').toLowerCase()}{t.acted_at ? ` · ${dayjs(t.acted_at).format('DD MMM HH:mm')}` : ''}{t.comment ? <><br />“{t.comment}”</> : null}</div>}>
                    <span style={{ display: 'inline-block', borderRadius: '50%', boxShadow: ring(t.status) }}><UserAvatar user={t.assignee} size={26} /></span>
                  </Tooltip>
                ))}
                {people.length > 4 && <Avatar size={26} radius="xl">+{people.length - 4}</Avatar>}
              </Avatar.Group>
            )}
            {!compact && s.status === 'ACTIVE' && s.due_at && <Text size="xs" mt={4} c={dayjs(s.due_at).isBefore(dayjs()) ? 'red' : 'dimmed'}>Due {dayjs(s.due_at).fromNow()}</Text>}
            {!compact && s.status === 'DONE' && s.ended_at && <Text size="xs" mt={4} c="dimmed">{dayjs(s.ended_at).format('DD MMM, HH:mm')}</Text>}
          </div>
        )
      })}
    </div>
  )
}

export function MiniStages({ stages, index }: { stages: { key: string; name: string }[]; index: number }) {
  return (
    <Group gap={3} wrap="nowrap">
      {stages.map((s, i) => (
        <Tooltip key={s.key} label={s.name}>
          <span style={{ display: 'inline-block', width: 16, height: 5, borderRadius: 3, background: i < index ? '#22c55e' : i === index ? '#2563eb' : 'var(--elm-border)' }} />
        </Tooltip>
      ))}
    </Group>
  )
}
