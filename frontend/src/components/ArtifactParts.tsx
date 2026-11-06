import { ActionIcon, Alert, Badge, Button, Group, Modal, MultiSelect, Select, Stack, Text, Textarea, TextInput, Timeline, Tooltip } from '@mantine/core'
import { IconCheck, IconLink, IconTrash, IconX } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import { useAction, useUsers } from '../api/hooks'
import { Hash, When } from './common'

/** Pick reviewers (optional, decide first) and approvers (at least one). The server enforces separation of duties. */
export function SubmitReviewModal({ opened, onClose, title, onSubmit, loading, exclude = [] }: { opened: boolean; onClose: () => void; title: string; onSubmit: (v: { reviewers: string[]; approvers: string[] }) => void; loading?: boolean; exclude?: string[] }) {
  const users = useUsers()
  const [reviewers, setReviewers] = useState<string[]>([])
  const [approvers, setApprovers] = useState<string[]>([])
  const data = (users.data || []).filter((u) => !exclude.includes(u.id)).map((u) => ({ value: u.id, label: `${u.full_name} (${u.username})` }))
  return (
    <Modal opened={opened} onClose={onClose} title={title}>
      <Stack>
        <MultiSelect label="Reviewers (optional)" description="Decide first" searchable data={data.filter((d) => !approvers.includes(d.value))} value={reviewers} onChange={setReviewers} />
        <MultiSelect label="Approvers" description="At least one; they decide after every reviewer has approved" required searchable data={data.filter((d) => !reviewers.includes(d.value))} value={approvers} onChange={setApprovers} />
        <Text size="xs" c="dimmed">Decisions are bound to the current revision and its SHA-256. The owner and you cannot review your own work.</Text>
        <Group justify="flex-end"><Button variant="default" onClick={onClose}>Cancel</Button><Button disabled={!approvers.length} loading={loading} onClick={() => onSubmit({ reviewers, approvers })}>Submit for review</Button></Group>
      </Stack>
    </Modal>
  )
}

const DECISION_COLOR: Record<string, string> = { APPROVED: 'teal', CHANGES_REQUESTED: 'orange', PENDING: 'blue', SUPERSEDED: 'gray' }

/** Review list with decision controls for the current user's pending reviews. */
export function ReviewPanel({ reviews, decideUrl, keys }: { reviews: any[]; decideUrl: (id: string) => string; keys: any[][] }) {
  const [comment, setComment] = useState('')
  const decide = useAction((v: { id: string; decision: string }) => api.post(decideUrl(v.id), { decision: v.decision, comment }), { success: 'Decision recorded', invalidate: keys, onDone: () => setComment('') })
  const mine = reviews.find((r) => r.mine)
  if (!reviews.length) return <Text size="sm" c="dimmed">Not submitted for review yet.</Text>
  return (
    <Stack>
      {mine && (
        <Alert color="blue" title={`Your ${mine.role.toLowerCase()} decision on revision ${mine.revision}`}>
          <Stack gap="xs">
            <Textarea placeholder="Comment (required to request changes)" autosize minRows={2} value={comment} onChange={(e) => setComment(e.currentTarget.value)} />
            <Group gap="xs">
              <Button size="xs" color="teal" leftSection={<IconCheck size={14} />} loading={decide.isPending} onClick={() => decide.mutate({ id: mine.id, decision: 'approve' })}>Approve</Button>
              <Button size="xs" color="orange" variant="light" leftSection={<IconX size={14} />} disabled={!comment.trim()} loading={decide.isPending} onClick={() => decide.mutate({ id: mine.id, decision: 'request_changes' })}>Request changes</Button>
            </Group>
          </Stack>
        </Alert>
      )}
      <Stack gap={6}>
        {reviews.map((r) => (
          <Group key={r.id} justify="space-between" wrap="nowrap">
            <Group gap={6} wrap="nowrap">
              <Badge size="xs" variant="outline">cycle {r.cycle}</Badge>
              <Text size="sm">{r.reviewer?.full_name}</Text>
              <Text size="xs" c="dimmed">{r.role.toLowerCase()} · rev {r.revision}</Text>
              <Hash value={r.sha256} />
            </Group>
            <Group gap={6} wrap="nowrap">
              {r.comment && <Tooltip label={r.comment} multiline w={300}><Text size="xs" c="dimmed" lineClamp={1} maw={180}>{r.comment}</Text></Tooltip>}
              <Badge size="xs" color={DECISION_COLOR[r.status]}>{r.status.replace(/_/g, ' ').toLowerCase()}</Badge>
              {r.decided_at && <When at={r.decided_at} />}
            </Group>
          </Group>
        ))}
      </Stack>
    </Stack>
  )
}

/** Traceability links with an "add link" row that searches requirements of the project (or takes an ID for other types). */
export function LinksPanel({ links, projectId, addUrl, removeUrl, keys, canEdit, types, linkTypes, withSection = false }: {
  links: any[]; projectId: string; addUrl: string; removeUrl?: (id: string) => string; keys: any[][]; canEdit: boolean; types: string[]; linkTypes: string[]; withSection?: boolean
}) {
  const [toType, setToType] = useState(types[0])
  const [target, setTarget] = useState<string | null>(null)
  const [linkType, setLinkType] = useState(linkTypes[0])
  const [section, setSection] = useState('')
  const reqs = useQuery<any>({ queryKey: ['requirements', projectId, '', null, null, null], queryFn: () => api.get(`/projects/${projectId}/requirements`), enabled: canEdit && toType === 'REQUIREMENT' })
  const tasks = useQuery<any[]>({ queryKey: ['work-items', 'scope', projectId], queryFn: () => api.get('/work-items', { project_id: projectId }), enabled: canEdit && toType === 'TASK' })
  const designs = useQuery<any>({ queryKey: ['designs', projectId], queryFn: () => api.get(`/projects/${projectId}/designs`), enabled: canEdit && toType === 'DESIGN' })
  const cases = useQuery<any>({ queryKey: ['test-cases', projectId], queryFn: () => api.get(`/projects/${projectId}/test-cases`), enabled: canEdit && toType === 'TEST_CASE' })
  const docs = useQuery<any>({ queryKey: ['documents-mini', projectId], queryFn: () => api.get('/documents', { project_id: projectId, page_size: 200 }), enabled: canEdit && toType === 'DOCUMENT' })
  const options = (toType === 'REQUIREMENT' ? reqs.data?.items : toType === 'TASK' ? tasks.data : toType === 'DESIGN' ? designs.data?.items : toType === 'TEST_CASE' ? cases.data?.items : (docs.data?.items || docs.data)) || []
  const add = useAction(() => api.post(addUrl, { to_type: toType, to_id: target, link_type: linkType, section: section || undefined }), { success: 'Linked', invalidate: keys, onDone: () => { setTarget(null); setSection('') } })
  const del = useAction((id: string) => api.del(removeUrl!(id)), { success: 'Link removed', invalidate: keys })
  return (
    <Stack>
      {canEdit && (
        <Group align="flex-end" gap="xs" wrap="wrap">
          <Select size="xs" w={130} label="Record type" value={toType} onChange={(v) => { setToType(v!); setTarget(null) }} allowDeselect={false} data={types.map((t) => ({ value: t, label: t.replace('_', ' ').toLowerCase() }))} />
          <Select size="xs" style={{ flex: 1, minWidth: 220 }} label="Record" searchable value={target} onChange={setTarget} data={options.map((o: any) => ({ value: o.id, label: `${o.key || o.number} ${o.title}` }))} />
          <Select size="xs" w={130} label="Link" value={linkType} onChange={(v) => setLinkType(v!)} allowDeselect={false} data={linkTypes} />
          {withSection && <TextInput size="xs" w={150} label="Section" placeholder="e.g. 3.2" value={section} onChange={(e) => setSection(e.currentTarget.value)} />}
          <Button size="xs" leftSection={<IconLink size={14} />} disabled={!target} loading={add.isPending} onClick={() => add.mutate(undefined)}>Link</Button>
        </Group>
      )}
      {!links.length && <Text size="sm" c="dimmed">No links yet.</Text>}
      {links.map((l) => (
        <Group key={l.id} justify="space-between" wrap="nowrap">
          <Group gap={6} wrap="nowrap">
            <Badge size="xs" variant="outline" color="gray">{l.direction === 'in' ? `${l.link_type} (from)` : l.link_type}</Badge>
            <Badge size="xs" variant="light">{l.target.type.replace('_', ' ').toLowerCase()}</Badge>
            <Text size="sm" fw={600}>{l.target.key}</Text>
            <Text size="sm" lineClamp={1}>{l.target.title}</Text>
            {l.section && <Text size="xs" c="dimmed">§ {l.section}</Text>}
          </Group>
          <Group gap={6} wrap="nowrap">
            <Badge size="xs" color="gray">{String(l.target.status).replace(/_/g, ' ').toLowerCase()}</Badge>
            {canEdit && removeUrl && l.direction === 'out' && <ActionIcon size="sm" variant="subtle" color="red" onClick={() => del.mutate(l.id)}><IconTrash size={14} /></ActionIcon>}
          </Group>
        </Group>
      ))}
    </Stack>
  )
}

export function HistoryPanel({ history }: { history: any[] }) {
  const label = (e: any) => {
    if (e.kind === 'CREATED') return 'Created'
    if (e.kind === 'VERSION') return `Version ${e.to} saved`
    if (e.kind === 'RESTORE') return `Version ${e.from} restored as version ${e.to}`
    if (e.kind === 'DECISION') return `${String(e.from).toLowerCase()} decision: ${String(e.to).replace(/_/g, ' ').toLowerCase()}`
    if (e.kind === 'LINK') return e.to ? `Linked: ${e.to}` : `Link removed: ${e.from}`
    if (e.kind === 'EXECUTION') return `Executed in ${e.from}: ${String(e.to).toLowerCase()}`
    return `${String(e.from ?? '').replace(/_/g, ' ').toLowerCase()} → ${String(e.to ?? '').replace(/_/g, ' ').toLowerCase()}`
  }
  return <Timeline bulletSize={14} lineWidth={2}>{history.map((e) => <Timeline.Item key={e.id} title={<Group gap={6}><Text size="xs" fw={600}>{e.actor?.full_name || 'System'}</Text><When at={e.at} /></Group>}><Text size="sm" c="dimmed">{label(e)}{e.comment ? `. ${e.comment}` : ''}</Text></Timeline.Item>)}</Timeline>
}

export function ReasonModal({ opened, title, onClose, onConfirm, loading, label = 'Reason' }: { opened: boolean; title: string; onClose: () => void; onConfirm: (reason: string) => void; loading?: boolean; label?: string }) {
  const [reason, setReason] = useState('')
  return (
    <Modal opened={opened} onClose={onClose} title={title}>
      <Stack>
        <Textarea label={label} required autosize minRows={3} autoFocus value={reason} onChange={(e) => setReason(e.currentTarget.value)} />
        <Group justify="flex-end"><Button variant="default" onClick={onClose}>Cancel</Button><Button disabled={reason.trim().length < 3} loading={loading} onClick={() => { onConfirm(reason); setReason('') }}>Confirm</Button></Group>
      </Stack>
    </Modal>
  )
}
