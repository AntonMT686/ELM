import { ActionIcon, Alert, Badge, Button, Card, Grid, Group, Menu, MultiSelect, NumberInput, Select, Stack, Switch, Table, Tabs, TagsInput, Text, Textarea, TextInput, Title, Tooltip } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconArrowLeft, IconArrowRight, IconChevronLeft, IconChevronRight, IconDeviceFloppy, IconPlus, IconRocket, IconTrash } from '@tabler/icons-react'
import { Background, Controls, Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps } from '@xyflow/react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, errorText } from '../api/client'
import { useAction, useDocTypes, useDomains, useMe, useOrgUnits, useRoles } from '../api/hooks'
import { When } from '../components/common'

const TYPE_META: Record<string, { color: string; label: string }> = {
  prepare: { color: '#64748b', label: 'Prepare' }, review: { color: '#2563eb', label: 'Review' }, approval: { color: '#7c3aed', label: 'Approval' },
  signature: { color: '#d97706', label: 'Signature' }, acknowledge: { color: '#0891b2', label: 'Acknowledge' },
}

function StageNode({ data }: NodeProps) {
  const s: any = data.stage
  const m = TYPE_META[s.type]
  return (
    <div className={`wf-node ${data.selected ? 'selected' : ''}`} style={{ borderTop: `4px solid ${m.color}` }}>
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <div className="k" style={{ color: m.color }}>{m.label}{s.mode && s.type !== 'prepare' && s.type !== 'signature' ? ` · ${s.mode}${s.mode === 'quorum' ? ' ' + s.quorum : ''}` : ''}</div>
      <div style={{ fontWeight: 650, fontSize: 14, marginTop: 2 }}>{s.name}</div>
      <div style={{ fontSize: 11.5, opacity: 0.7, marginTop: 4 }}>
        {s.type === 'prepare' ? 'Initiator' : s.type === 'signature' ? `Signers: ${(s.signers_from || []).join(', ')}` : s.assignee?.kind === 'role' ? `Auto: role ${s.assignee.role_code}` : s.assignee?.kind === 'pick' ? `Picked${s.assignee.role_code ? ` (${s.assignee.role_code})` : ''}` : 'Named users'}
      </div>
      <div style={{ fontSize: 11, opacity: 0.6, marginTop: 2 }}>{s.sla_hours ? `SLA ${s.sla_hours}h` : ''}{s.checklist?.length ? ` · ${s.checklist.length} checks` : ''}{s.sod_exclude?.length ? ' · SoD' : ''}{s.skip_if ? ' · conditional' : ''}</div>
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </div>
  )
}
const nodeTypes = { stage: StageNode }

export default function WorkflowDesignerPage() {
  const { id } = useParams()
  const nav = useNavigate()
  const qc = useQueryClient()
  const roles = useRoles()
  const { data: def } = useQuery<any>({ queryKey: ['workflow', id], queryFn: () => api.get(`/workflow-definitions/${id}`) })
  const [spec, setSpec] = useState<any>(null)
  const [sel, setSel] = useState(0)
  const [errors, setErrors] = useState<string[]>([])
  const [dirty, setDirty] = useState(false)
  useEffect(() => { if (def && !spec) setSpec(def.draft_spec) }, [def])

  const stages: any[] = spec?.stages || []
  const update = (patch: any) => { setSpec({ ...spec, stages: stages.map((s, i) => (i === sel ? { ...s, ...patch } : s)) }); setDirty(true) }
  const { nodes, edges } = useMemo(() => {
    const nodes: Node[] = stages.map((s, i) => ({ id: s.key, type: 'stage', position: { x: i * 250, y: i % 2 ? 40 : 0 }, data: { stage: s, selected: i === sel } }))
    const edges: Edge[] = stages.slice(1).map((s, i) => ({ id: `e${i}`, source: stages[i].key, target: s.key, animated: true, markerEnd: { type: MarkerType.ArrowClosed }, label: s.skip_if ? 'if…' : undefined }))
    stages.forEach((s, i) => { if (i > 1 && s.type !== 'signature') edges.push({ id: `r${i}`, source: s.key, target: stages[0].key, type: 'smoothstep', style: { stroke: '#f87171', strokeDasharray: 4 }, label: 'changes requested', labelStyle: { fontSize: 9, fill: '#ef4444' } }) })
    return { nodes, edges }
  }, [spec, sel])

  const save = async () => {
    try {
      const r = await api.put(`/workflow-definitions/${id}/draft`, spec)
      setErrors(r.errors)
      setDirty(false)
      notifications.show({ color: r.errors.length ? 'orange' : 'teal', message: r.errors.length ? `Draft saved with ${r.errors.length} issue(s) to fix before publishing` : 'Draft saved — ready to publish' })
      qc.invalidateQueries({ queryKey: ['workflow', id] })
      return r.errors as string[]
    } catch (e) { notifications.show({ color: 'red', message: errorText(e) }); return ['save failed'] }
  }
  const publish = useAction(async () => { const errs = await save(); if (errs.length) throw new Error('Fix validation issues first.'); return api.post(`/workflow-definitions/${id}/publish`) }, {
    success: (r: any) => `Published v${r.version_no}. New submissions use it; running reviews keep their version.`, invalidate: [['workflow', id], ['workflows']],
  })
  const add = (type: string) => {
    const key = `${type}_${stages.length}`
    const s: any = { key, name: TYPE_META[type].label, type, assignee: { kind: 'pick', min: 1 }, mode: 'all', sla_hours: 72, sod_exclude: ['prepare'], checklist: [], weight: 10, signers_from: type === 'signature' ? stages.filter((x) => x.type !== 'signature').map((x) => x.key) : [] }
    const idx = type === 'signature' ? stages.length : Math.max(1, stages.findIndex((x) => x.type === 'signature') === -1 ? stages.length : stages.findIndex((x) => x.type === 'signature'))
    const next = [...stages]; next.splice(idx, 0, s)
    setSpec({ ...spec, stages: next }); setSel(idx); setDirty(true)
  }
  const moveSel = (d: number) => { const j = sel + d; if (sel === 0 || j < 1 || j >= stages.length) return; const n = [...stages]; [n[sel], n[j]] = [n[j], n[sel]]; setSpec({ ...spec, stages: n }); setSel(j); setDirty(true) }
  const remove = () => { if (sel === 0) return; setSpec({ ...spec, stages: stages.filter((_, i) => i !== sel) }); setSel(Math.max(0, sel - 1)); setDirty(true) }
  const s = stages[sel]
  const earlier = stages.slice(0, sel).map((x) => ({ value: x.key, label: x.name }))
  if (!def || !spec) return null

  return (
    <div className="page" style={{ maxWidth: 1800 }}>
      <Group justify="space-between" mb="md">
        <Group><ActionIcon variant="subtle" onClick={() => nav('/workflows')}><IconArrowLeft /></ActionIcon><div><Title order={3}>{def.name}</Title><Text size="sm" c="dimmed">{def.code} · {def.latest_version ? `v${def.latest_version} published` : 'never published'} · {def.running_instances} running</Text></div></Group>
        <Group>
          {dirty && <Badge color="orange">unsaved</Badge>}
          <Select size="xs" w={190} value={spec.on_complete} onChange={(v) => { setSpec({ ...spec, on_complete: v }); setDirty(true) }} data={[{ value: 'approve', label: 'On completion: Approve' }, { value: 'release', label: 'On completion: Auto-release' }]} />
          <Menu><Menu.Target><Button variant="default" leftSection={<IconPlus size={16} />}>Add stage</Button></Menu.Target>
            <Menu.Dropdown>{['review', 'approval', 'acknowledge', 'signature'].map((t) => <Menu.Item key={t} leftSection={<span style={{ width: 10, height: 10, borderRadius: 3, background: TYPE_META[t].color }} />} onClick={() => add(t)}>{TYPE_META[t].label} stage</Menu.Item>)}</Menu.Dropdown>
          </Menu>
          <Button variant="default" leftSection={<IconDeviceFloppy size={16} />} onClick={save}>Save draft</Button>
          <Button leftSection={<IconRocket size={16} />} loading={publish.isPending} onClick={() => publish.mutate(undefined)}>Validate & publish</Button>
        </Group>
      </Group>
      {errors.length > 0 && <Alert color="orange" mb="md" title="Fix before publishing">{errors.map((e, i) => <div key={i}>• {e}</div>)}</Alert>}
      <Grid gutter="md">
        <Grid.Col span={{ base: 12, xl: 8 }}>
          <Card p={0} style={{ height: 420, overflow: 'hidden' }}>
            <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView onNodeClick={(_, n) => setSel(stages.findIndex((x) => x.key === n.id))} nodesDraggable={false} proOptions={{ hideAttribution: true }}>
              <Background gap={20} /><Controls showInteractive={false} />
            </ReactFlow>
          </Card>
          <Tabs defaultValue="bindings" mt="md">
            <Tabs.List><Tabs.Tab value="bindings">Where it applies ({def.bindings.filter((b: any) => b.active).length})</Tabs.Tab><Tabs.Tab value="versions">Versions ({def.versions.length})</Tabs.Tab></Tabs.List>
            <Tabs.Panel value="bindings" pt="md"><Bindings def={def} /></Tabs.Panel>
            <Tabs.Panel value="versions" pt="md">
              <Table><Table.Tbody>{def.versions.map((v: any) => <Table.Tr key={v.id}><Table.Td><b>v{v.version_no}</b></Table.Td><Table.Td><Badge color={v.status === 'PUBLISHED' ? 'teal' : 'gray'}>{v.status}</Badge></Table.Td><Table.Td>{v.published_by?.full_name}</Table.Td><Table.Td><When at={v.published_at} /></Table.Td><Table.Td><span className="hash">{v.sha256.slice(0, 16)}</span></Table.Td></Table.Tr>)}</Table.Tbody></Table>
            </Tabs.Panel>
          </Tabs>
        </Grid.Col>
        <Grid.Col span={{ base: 12, xl: 4 }}>
          {s && (
            <Card>
              <Group justify="space-between" mb="sm">
                <Group gap={6}><span style={{ width: 12, height: 12, borderRadius: 3, background: TYPE_META[s.type].color }} /><Text fw={650}>Stage {sel + 1}: {TYPE_META[s.type].label}</Text></Group>
                <Group gap={4}>
                  <Tooltip label="Move earlier"><ActionIcon variant="default" disabled={sel <= 1} onClick={() => moveSel(-1)}><IconChevronLeft size={16} /></ActionIcon></Tooltip>
                  <Tooltip label="Move later"><ActionIcon variant="default" disabled={sel === 0 || sel >= stages.length - 1} onClick={() => moveSel(1)}><IconChevronRight size={16} /></ActionIcon></Tooltip>
                  <Tooltip label="Remove stage"><ActionIcon color="red" variant="light" disabled={sel === 0} onClick={remove}><IconTrash size={16} /></ActionIcon></Tooltip>
                </Group>
              </Group>
              <Stack gap="sm">
                <TextInput label="Stage name" value={s.name} onChange={(e) => update({ name: e.currentTarget.value })} />
                {s.type !== 'prepare' && s.type !== 'signature' && (
                  <>
                    <Group grow>
                      <Select label="Who acts" value={s.assignee.kind} onChange={(v) => update({ assignee: { ...s.assignee, kind: v } })} data={[{ value: 'pick', label: 'Picked by submitter' }, { value: 'role', label: 'Everyone with role' }]} />
                      <Select label="Eligible role" clearable value={s.assignee.role_code || null} onChange={(v) => update({ assignee: { ...s.assignee, role_code: v } })} data={(roles.data || []).map((r: any) => ({ value: r.code, label: r.name }))} />
                    </Group>
                    {s.assignee.kind === 'pick' && <Group grow><NumberInput label="Min people" min={1} value={s.assignee.min} onChange={(v) => update({ assignee: { ...s.assignee, min: Number(v) || 1 } })} /><NumberInput label="Max people" min={1} value={s.assignee.max ?? ''} onChange={(v) => update({ assignee: { ...s.assignee, max: v === '' ? null : Number(v) } })} /></Group>}
                    <Group grow>
                      <Select label="Completion rule" value={s.mode} onChange={(v) => update({ mode: v })} data={[{ value: 'all', label: 'All must accept (sequential/parallel)' }, { value: 'any', label: 'Any one accepts' }, { value: 'quorum', label: 'Quorum' }]} />
                      {s.mode === 'quorum' && <NumberInput label="Quorum" min={1} value={s.quorum || 2} onChange={(v) => update({ quorum: Number(v) })} />}
                    </Group>
                    <MultiSelect label="Separation of duties — cannot be the same person as" data={earlier} value={s.sod_exclude || []} onChange={(v) => update({ sod_exclude: v })} />
                    <TagsInput label="Review checklist (press Enter to add)" value={s.checklist || []} onChange={(v) => update({ checklist: v })} />
                    <Switch label="Allow outright rejection" checked={s.allow_reject !== false} onChange={(e) => update({ allow_reject: e.currentTarget.checked })} />
                  </>
                )}
                {s.type === 'signature' && <MultiSelect label="Signed by the actors of" data={earlier} value={s.signers_from || []} onChange={(v) => update({ signers_from: v })} description="Skipped automatically when the document type does not require a signature." />}
                {s.type !== 'prepare' && <Group grow><NumberInput label="SLA (hours)" min={1} value={s.sla_hours ?? ''} onChange={(v) => update({ sla_hours: v === '' ? null : Number(v) })} /><NumberInput label="Progress weight %" min={0} max={100} value={s.weight || 0} onChange={(v) => update({ weight: Number(v) })} /></Group>}
                {s.type !== 'prepare' && (
                  <Group grow align="flex-end">
                    <Select label="Skip this stage when" clearable value={s.skip_if?.field || null} onChange={(v) => update({ skip_if: v ? { field: v, op: 'eq', value: s.skip_if?.value || '' } : null })} data={[{ value: 'classification', label: 'Classification' }, { value: 'doc_type', label: 'Document type code' }, { value: 'domain', label: 'Domain' }, { value: 'level', label: 'Breakdown level' }, { value: 'category', label: 'Category' }]} />
                    {s.skip_if && <TextInput label="equals" value={s.skip_if.value} onChange={(e) => update({ skip_if: { ...s.skip_if, value: e.currentTarget.value } })} />}
                  </Group>
                )}
                <Textarea label="Instructions shown to the actor" autosize minRows={2} value={s.instructions || ''} onChange={(e) => update({ instructions: e.currentTarget.value })} />
              </Stack>
            </Card>
          )}
          <Alert mt="md" variant="light" icon={<IconArrowRight size={16} />}>Any reviewer can <b>request changes</b>; the document returns to the author and a new cycle starts on the updated content (red dashed paths).</Alert>
        </Grid.Col>
      </Grid>
    </div>
  )
}

function Bindings({ def }: { def: any }) {
  const types = useDocTypes()
  const domains = useDomains()
  const orgs = useOrgUnits()
  const { data: me } = useMe()
  const [b, setB] = useState<any>({ priority: 0 })
  const add = useAction(() => api.post(`/workflow-definitions/${def.id}/bindings`, b), { success: 'Binding added', invalidate: [['workflow', def.id], ['workflows']], onDone: () => setB({ priority: 0 }) })
  const rm = useAction((bid: string) => api.del(`/workflow-bindings/${bid}`), { success: 'Binding removed', invalidate: [['workflow', def.id]] })
  const name = (list: any[] | undefined, id?: string, k = 'name') => list?.find((x) => x.id === id)?.[k]
  return (
    <Stack>
      <Text size="sm" c="dimmed">The most specific matching binding wins (more criteria = more specific; then priority). An empty binding is the catch-all default.</Text>
      <Table>
        <Table.Thead><Table.Tr><Table.Th>Document type</Table.Th><Table.Th>Domain</Table.Th><Table.Th>Project</Table.Th><Table.Th>Directorate</Table.Th><Table.Th>Level</Table.Th><Table.Th>Priority</Table.Th><Table.Th /></Table.Tr></Table.Thead>
        <Table.Tbody>
          {def.bindings.filter((x: any) => x.active).map((x: any) => (
            <Table.Tr key={x.id}><Table.Td>{x.document_type?.name || <Text c="dimmed" size="sm">any</Text>}</Table.Td><Table.Td>{name(domains.data, x.domain_id) || '—'}</Table.Td><Table.Td>{me?.projects.find((p) => p.id === x.project_id)?.code || '—'}</Table.Td>
              <Table.Td>{name(orgs.data, x.org_unit_id, 'code') || '—'}</Table.Td><Table.Td>{x.level_code || '—'}</Table.Td><Table.Td>{x.priority}</Table.Td>
              <Table.Td><ActionIcon color="red" variant="subtle" onClick={() => rm.mutate(x.id)}><IconTrash size={14} /></ActionIcon></Table.Td></Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      <Card withBorder p="sm">
        <Text size="sm" fw={600} mb={6}>Add binding</Text>
        <Group grow>
          <Select placeholder="Document type" clearable value={b.document_type_id || null} onChange={(v) => setB({ ...b, document_type_id: v })} data={(types.data || []).map((t) => ({ value: t.id, label: t.name }))} />
          <Select placeholder="Domain" clearable value={b.domain_id || null} onChange={(v) => setB({ ...b, domain_id: v })} data={(domains.data || []).map((t: any) => ({ value: t.id, label: t.name }))} />
          <Select placeholder="Project" clearable value={b.project_id || null} onChange={(v) => setB({ ...b, project_id: v })} data={(me?.projects || []).map((p) => ({ value: p.id, label: p.code }))} />
          <Select placeholder="Directorate" clearable searchable value={b.org_unit_id || null} onChange={(v) => setB({ ...b, org_unit_id: v })} data={(orgs.data || []).map((o: any) => ({ value: o.id, label: o.code }))} />
          <TextInput placeholder="Level code" value={b.level_code || ''} onChange={(e) => setB({ ...b, level_code: e.currentTarget.value.toUpperCase() || null })} />
          <Button onClick={() => add.mutate(undefined)} loading={add.isPending}>Add</Button>
        </Group>
      </Card>
    </Stack>
  )
}
