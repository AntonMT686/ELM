import { ActionIcon, Avatar, Badge, CopyButton, Group, Stack, Text, ThemeIcon, Title, Tooltip } from '@mantine/core'
import {
  IconAlertTriangle, IconCheck, IconCircleCheck, IconCircleX, IconClock, IconCopy, IconFile, IconFileSpreadsheet, IconFileTypeDoc, IconFileTypePdf,
  IconFileTypePpt, IconLoader2, IconLock, IconPencil, IconPhoto, IconRosetteDiscountCheck, IconBan, IconInbox,
} from '@tabler/icons-react'
import dayjs from 'dayjs'
import type { ReactNode } from 'react'
import type { UserBrief } from '../api/types'

export const STATUS: Record<string, { color: string; label: string; icon: ReactNode }> = {
  DRAFT: { color: 'gray', label: 'Draft', icon: <IconPencil size={12} /> },
  IN_REVIEW: { color: 'blue', label: 'In review', icon: <IconLoader2 size={12} /> },
  CHANGES_REQUESTED: { color: 'orange', label: 'Changes requested', icon: <IconAlertTriangle size={12} /> },
  REJECTED: { color: 'red', label: 'Rejected', icon: <IconCircleX size={12} /> },
  APPROVED: { color: 'cyan', label: 'Approved', icon: <IconCircleCheck size={12} /> },
  RELEASED: { color: 'teal', label: 'Released', icon: <IconRosetteDiscountCheck size={12} /> },
  SUPERSEDED: { color: 'gray', label: 'Superseded', icon: <IconBan size={12} /> },
  WITHDRAWN: { color: 'red', label: 'Withdrawn', icon: <IconBan size={12} /> },
  PENDING: { color: 'blue', label: 'Pending', icon: <IconClock size={12} /> },
  SIGNED: { color: 'teal', label: 'Signed', icon: <IconRosetteDiscountCheck size={12} /> },
  CANCELLED: { color: 'gray', label: 'Cancelled', icon: <IconBan size={12} /> },
  REASSIGNED: { color: 'gray', label: 'Reassigned', icon: null },
  ACTIVE: { color: 'blue', label: 'Active', icon: <IconLoader2 size={12} /> },
  COMPLETED: { color: 'teal', label: 'Completed', icon: <IconCheck size={12} /> },
  DONE: { color: 'teal', label: 'Done', icon: <IconCheck size={12} /> },
  TODO: { color: 'gray', label: 'To do', icon: null },
  IN_PROGRESS: { color: 'blue', label: 'In progress', icon: null },
  BLOCKED: { color: 'red', label: 'Blocked', icon: null },
  RETURNED: { color: 'orange', label: 'Returned', icon: null },
  SKIPPED: { color: 'gray', label: 'Skipped', icon: null },
  OPEN: { color: 'gray', label: 'Open', icon: null },
  REVIEW: { color: 'violet', label: 'In review', icon: null },
  ON_HOLD: { color: 'yellow', label: 'On hold', icon: null },
  NOT_STARTED: { color: 'gray', label: 'Not started', icon: null },
  PLANNED: { color: 'gray', label: 'Planned', icon: null },
  ACHIEVED: { color: 'teal', label: 'Achieved', icon: <IconCheck size={12} /> },
  ARCHIVED: { color: 'gray', label: 'Archived', icon: null },
  CLOSED: { color: 'gray', label: 'Closed', icon: null },
}

export function StatusTag({ status, locked }: { status?: string | null; locked?: boolean }) {
  if (!status) return null
  const s = STATUS[status] || { color: 'gray', label: status.replace(/_/g, ' ').toLowerCase(), icon: null }
  return (
    <Badge color={s.color} variant="light" radius="xl" leftSection={s.icon} rightSection={locked ? <IconLock size={10} /> : undefined} style={{ textTransform: 'none', fontWeight: 600 }}>
      {s.label}
    </Badge>
  )
}

export function TypeBadge({ type }: { type?: { code: string; name: string; color?: string } }) {
  if (!type) return null
  return <Tooltip label={type.name}><span className="lvl" style={{ background: type.color || '#64748b' }}>{type.code}</span></Tooltip>
}

const LEVEL_COLORS: Record<string, string> = { PRODUCT: '#1677ff', SYSTEM: '#722ed1', SUBSYSTEM: '#13c2c2', UNIT: '#fa8c16', MODULE: '#8c8c8c', COMPONENT: '#eb2f96' }
export function LevelTag({ level, color }: { level: string; color?: string }) {
  return <span className="lvl" style={{ background: color || LEVEL_COLORS[level] || '#64748b' }}>{level}</span>
}

const AV = ['blue', 'violet', 'cyan', 'teal', 'orange', 'pink', 'indigo', 'grape']
export function initials(name?: string) {
  if (!name) return '?'
  const p = name.replace(/^(Dr\.|Mr\.|Ms\.|Mrs\.)\s*/i, '').split(/\s+/)
  return ((p[0]?.[0] || '') + (p[1]?.[0] || '')).toUpperCase()
}
export const avatarColor = (id: string) => AV[[...id].reduce((a, c) => a + c.charCodeAt(0), 0) % AV.length]

export function UserAvatar({ user, size = 28, showName = false, sub }: { user?: UserBrief | null; size?: number; showName?: boolean; sub?: ReactNode }) {
  if (!user) return <Text c="dimmed" size="sm">—</Text>
  const av = <Avatar size={size} radius="xl" color={avatarColor(user.id)} variant="filled" style={{ flex: 'none' }}>{initials(user.full_name)}</Avatar>
  if (!showName) return <Tooltip label={`${user.full_name}${user.designation ? ' · ' + user.designation : ''}`}>{av}</Tooltip>
  return (
    <Group gap={8} wrap="nowrap" style={{ minWidth: 0 }}>
      {av}
      <div style={{ lineHeight: 1.2, minWidth: 0 }}>
        <Text size="sm" fw={500} truncate>{user.full_name}</Text>
        <Text size="xs" c="dimmed" truncate>{sub ?? user.designation}</Text>
      </div>
    </Group>
  )
}

export function FileIcon({ ext, size = 18 }: { ext?: string | null; size?: number }) {
  switch (ext) {
    case 'docx': case 'doc': return <IconFileTypeDoc size={size} color="#2b579a" />
    case 'xlsx': case 'xls': return <IconFileSpreadsheet size={size} color="#217346" />
    case 'pptx': case 'ppt': return <IconFileTypePpt size={size} color="#d24726" />
    case 'pdf': return <IconFileTypePdf size={size} color="#dc2626" />
    case 'png': case 'jpg': case 'jpeg': return <IconPhoto size={size} color="#7c3aed" />
    default: return <IconFile size={size} color="#94a3b8" />
  }
}

export function When({ at, prefix }: { at?: string | null; prefix?: string }) {
  if (!at) return <Text span c="dimmed">—</Text>
  const d = dayjs(at)
  return <Tooltip label={d.format('DD MMM YYYY, HH:mm')}><span>{prefix}{d.fromNow()}</span></Tooltip>
}

export function PageTitle({ title, sub, extra, icon }: { title: ReactNode; sub?: ReactNode; extra?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="page-title">
      <Group gap={12} wrap="nowrap">
        {icon && <ThemeIcon size={42} radius={12} variant="gradient" gradient={{ from: 'brand.7', to: 'cyan.5', deg: 135 }}>{icon}</ThemeIcon>}
        <div>
          <Title order={2} fz={22}>{title}</Title>
          {sub && <Text c="dimmed" size="sm">{sub}</Text>}
        </div>
      </Group>
      {extra && <Group gap="xs">{extra}</Group>}
    </div>
  )
}

export function EmptyBlock({ text, action, icon }: { text: string; action?: ReactNode; icon?: ReactNode }) {
  return (
    <Stack align="center" gap={8} py={36}>
      <ThemeIcon size={52} radius="xl" variant="light" color="gray">{icon || <IconInbox size={26} />}</ThemeIcon>
      <Text c="dimmed" size="sm" ta="center">{text}</Text>
      {action}
    </Stack>
  )
}

export function Hash({ value, short = true }: { value?: string | null; short?: boolean }) {
  if (!value) return null
  return (
    <Group gap={2} wrap="nowrap" display="inline-flex">
      <span className="hash">{short ? `${value.slice(0, 10)}…${value.slice(-6)}` : value}</span>
      <CopyButton value={value}>
        {({ copied, copy }) => (
          <Tooltip label={copied ? 'Copied' : 'Copy SHA-256'}>
            <ActionIcon size="xs" variant="subtle" color={copied ? 'teal' : 'gray'} onClick={(e) => { e.stopPropagation(); copy() }}>{copied ? <IconCheck size={12} /> : <IconCopy size={12} />}</ActionIcon>
          </Tooltip>
        )}
      </CopyButton>
    </Group>
  )
}

export const fmtSize = (n?: number) => (!n ? '—' : n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`)

const CLASS_COLORS: Record<string, string> = { UNCLASSIFIED: 'green', RESTRICTED: 'yellow', CONFIDENTIAL: 'orange', SECRET: 'red' }
export function ClassTag({ value }: { value?: string }) {
  if (!value) return null
  return <Badge size="sm" variant="light" color={CLASS_COLORS[value] || 'gray'}>{value}</Badge>
}

export function Kpi({ label, value, icon, color, hint, onClick }: { label: string; value?: ReactNode; icon: ReactNode; color: string; hint?: ReactNode; onClick?: () => void }) {
  return (
    <div className="kpi" onClick={onClick}>
      <ThemeIcon className="icon" size={38} radius="md" variant="light" color={color}>{icon}</ThemeIcon>
      <div className="label">{label}</div>
      <div className="value">{value ?? '–'}</div>
      {hint && <div className="hint">{hint}</div>}
    </div>
  )
}
