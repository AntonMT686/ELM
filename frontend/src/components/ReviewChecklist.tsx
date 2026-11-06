import { ActionIcon, Badge, Button, Card, Group, MultiSelect, SegmentedControl, Stack, Text, Textarea, TextInput, Tooltip } from '@mantine/core'
import { IconArrowDown, IconArrowUp, IconPlus, IconTrash } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { useAction } from '../api/hooks'
import { When } from './common'

export type Answer = { result?: 'OK' | 'NOT_OK' | 'NA'; remark?: string }
const RESULT_COLOR: Record<string, string> = { OK: 'teal', NOT_OK: 'red', NA: 'gray' }
const RESULT_LABEL: Record<string, string> = { OK: 'OK', NOT_OK: 'Not OK', NA: 'N/A' }

/** True when every item is answered, remarks are given where needed, and nothing is Not OK. */
export function checklistReady(items: any[], answers: Record<string, Answer>) {
  return items.every((i) => {
    const a = answers[i.id]
    return a?.result && (a.result === 'OK' || (a.remark || '').trim()) && a.result !== 'NOT_OK'
  })
}

export function checklistNotOk(items: any[], answers: Record<string, Answer>) {
  return items.filter((i) => answers[i.id]?.result === 'NOT_OK')
}

/** Reviewer / approver answers the preparer's checklist item by item. */
export function ChecklistAnswerForm({ items, answers, onChange, earlier }: { items: any[]; answers: Record<string, Answer>; onChange: (a: Record<string, Answer>) => void; earlier?: any[] }) {
  const set = (id: string, patch: Answer) => onChange({ ...answers, [id]: { ...answers[id], ...patch } })
  const before = (text: string) => (earlier || []).flatMap((e: any) => e.answers).filter((a: any) => a.text === text)
  if (!items.length) return null
  return (
    <Stack gap={10} mb="md">
      <Text fw={600} size="sm">Preparer's checklist ({items.length})</Text>
      {items.map((i, n) => {
        const a = answers[i.id] || {}
        const prev = before(i.text)
        return (
          <Card key={i.id} withBorder p="xs">
            <Text size="sm" fw={500}>{n + 1}. {i.text}</Text>
            {i.guidance && <Text size="xs" c="dimmed">{i.guidance}</Text>}
            {!!prev.length && <Group gap={4} mt={2}>{prev.map((p: any, k: number) => <Tooltip key={k} label={`${p.by?.full_name || ''}${p.remark ? ': ' + p.remark : ''}`}><Badge size="xs" variant="outline" color={RESULT_COLOR[p.result]}>earlier: {RESULT_LABEL[p.result]}</Badge></Tooltip>)}</Group>}
            <SegmentedControl mt={6} size="xs" fullWidth value={a.result || ''} onChange={(v) => set(i.id, { result: v as Answer['result'] })}
              data={[{ value: 'OK', label: 'OK' }, { value: 'NOT_OK', label: 'Not OK' }, { value: 'NA', label: 'N/A' }]} color={a.result ? RESULT_COLOR[a.result] : undefined} />
            {a.result && a.result !== 'OK' && <TextInput mt={6} size="xs" required placeholder={a.result === 'NOT_OK' ? 'What is wrong and where (required)' : 'Why it does not apply (required)'} value={a.remark || ''} onChange={(e) => set(i.id, { remark: e.currentTarget.value })} />}
          </Card>
        )
      })}
    </Stack>
  )
}

/** Read-only view of answers recorded for one workflow task. */
export function ChecklistResults({ results }: { results: any[] }) {
  if (!results?.length) return null
  return (
    <Stack gap={2} mt={4}>
      {results.map((r: any) => (
        <Group key={r.item_id} gap={6} wrap="nowrap" align="flex-start">
          <Badge size="xs" color={RESULT_COLOR[r.result]} style={{ flexShrink: 0 }}>{RESULT_LABEL[r.result]}</Badge>
          <Text size="xs">{r.text}{r.remark ? <Text span c="dimmed"> — {r.remark}</Text> : null}</Text>
        </Group>
      ))}
    </Stack>
  )
}

/** The preparer writes the review checklist of the current revision. */
export function ChecklistEditor({ docId, view, keys }: { docId: string; view: any; keys: any[][] }) {
  const [rows, setRows] = useState<any[]>([])
  useEffect(() => setRows(view.items.map((i: any) => ({ text: i.text, guidance: i.guidance || '', stages: i.stages }))), [view.items.map((i: any) => i.id).join()])
  const save = useAction(() => api.put(`/documents/${docId}/review-checklist`, { items: rows.filter((r) => r.text.trim()).map((r) => ({ ...r, guidance: r.guidance || null })) }), { success: 'Review checklist saved', invalidate: keys })
  const upd = (n: number, patch: any) => setRows(rows.map((r, i) => (i === n ? { ...r, ...patch } : r)))
  const move = (n: number, d: number) => { const r = [...rows]; const [x] = r.splice(n, 1); r.splice(n + d, 0, x); setRows(r) }
  const stageData = view.stages.map((s: any) => ({ value: s.key, label: s.name }))
  return (
    <Stack>
      <Text size="sm" c="dimmed">
        Write what reviewers and approvers must check in revision {view.revision}. Each of them answers every item OK, Not OK or N/A with a remark, so you see exactly what to fix.
        {view.required ? ' This document type cannot be submitted without a checklist.' : ''} The checklist is frozen while the revision is in review.
      </Text>
      {rows.map((r, n) => (
        <Card key={n} withBorder p="xs">
          <Group align="flex-start" gap="xs" wrap="nowrap">
            <Text size="sm" fw={600} w={22} mt={6}>{n + 1}.</Text>
            <Stack gap={6} style={{ flex: 1 }}>
              <TextInput size="xs" placeholder="What must be true (e.g. Every requirement has a verification method)" disabled={!view.can_edit} value={r.text} onChange={(e) => upd(n, { text: e.currentTarget.value })} />
              <Group grow gap="xs">
                <Textarea size="xs" autosize minRows={1} placeholder="Guidance: where to look, acceptance hint (optional)" disabled={!view.can_edit} value={r.guidance} onChange={(e) => upd(n, { guidance: e.currentTarget.value })} />
                <MultiSelect size="xs" placeholder="All review and approval stages" disabled={!view.can_edit} data={stageData} value={r.stages} onChange={(v) => upd(n, { stages: v })} />
              </Group>
            </Stack>
            {view.can_edit && <Stack gap={2}>
              <ActionIcon size="sm" variant="subtle" disabled={n === 0} onClick={() => move(n, -1)}><IconArrowUp size={14} /></ActionIcon>
              <ActionIcon size="sm" variant="subtle" disabled={n === rows.length - 1} onClick={() => move(n, 1)}><IconArrowDown size={14} /></ActionIcon>
              <ActionIcon size="sm" variant="subtle" color="red" onClick={() => setRows(rows.filter((_, i) => i !== n))}><IconTrash size={14} /></ActionIcon>
            </Stack>}
          </Group>
        </Card>
      ))}
      {!rows.length && <Text size="sm" c="dimmed">No checklist items yet.</Text>}
      {view.can_edit && (
        <Group>
          <Button size="xs" variant="light" leftSection={<IconPlus size={14} />} onClick={() => setRows([...rows, { text: '', guidance: '', stages: [] }])}>Add item</Button>
          <Button size="xs" loading={save.isPending} onClick={() => save.mutate(undefined)}>Save checklist</Button>
        </Group>
      )}
      {!view.can_edit && <Text size="xs" c="dimmed">Read only: {view.revision ? `revision ${view.revision} is in review or released, or you cannot edit it` : 'no revision'}.</Text>}
    </Stack>
  )
}

export function AnsweredAt({ at }: { at?: string }) { return at ? <When at={at} /> : null }
