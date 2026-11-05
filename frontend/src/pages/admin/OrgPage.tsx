import { Badge, Button, Card, Grid, Group, Select, Stack, Switch, Text, Textarea, TextInput } from '@mantine/core'
import { IconBuildingCommunity, IconChevronDown, IconChevronRight, IconPlus } from '@tabler/icons-react'
import { useEffect, useMemo, useState } from 'react'
import { api } from '../../api/client'
import { useAction, useOrgUnits } from '../../api/hooks'
import { PageTitle } from '../../components/common'

const TYPES = ['ORGANIZATION', 'HEAD_DIRECTORATE', 'DIRECTORATE', 'DIVISION', 'DEPARTMENT', 'GROUP']
const COLOR: Record<string, string> = { ORGANIZATION: '#0f172a', HEAD_DIRECTORATE: '#db2777', DIRECTORATE: '#2563eb', DIVISION: '#7c3aed', DEPARTMENT: '#0891b2', GROUP: '#64748b' }

export default function OrgPage() {
  const { data = [] } = useOrgUnits()
  const [sel, setSel] = useState<any | null>(null)
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const kids = useMemo(() => { const m: Record<string, any[]> = {}; data.forEach((o) => (m[o.parent_id || 'root'] ||= []).push(o)); return m }, [data])
  useEffect(() => { const o: Record<string, boolean> = {}; data.forEach((u) => { if (u.unit_type === 'ORGANIZATION') o[u.id] = true }); setOpen((p) => ({ ...o, ...p })) }, [data])
  const Row = ({ o, depth }: { o: any; depth: number }) => (
    <>
      <div className={`tree-row ${sel?.id === o.id ? 'sel' : ''}`} style={{ paddingLeft: 6 + depth * 18 }} onClick={() => setSel(o)}>
        <span style={{ width: 18 }} onClick={(e) => { e.stopPropagation(); setOpen({ ...open, [o.id]: !open[o.id] }) }}>{kids[o.id] ? (open[o.id] ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />) : null}</span>
        <span className="lvl" style={{ background: COLOR[o.unit_type] }}>{o.unit_type.replace('_', ' ')}</span>
        <Text size="sm" fw={600}>{o.code}</Text><Text size="sm" c="dimmed" truncate style={{ flex: 1 }}>{o.name}</Text>
        {o.is_oversight && <Badge size="xs" color="pink">oversight</Badge>}{!o.active && <Badge size="xs" color="gray">inactive</Badge>}<Text size="xs" c="dimmed">{o.members}</Text>
      </div>
      {open[o.id] && (kids[o.id] || []).map((k) => <Row key={k.id} o={k} depth={depth + 1} />)}
    </>
  )
  return (
    <div className="page">
      <PageTitle icon={<IconBuildingCommunity size={22} />} title="Organization structure" sub="ADA → Head Directorate / Directorates → Divisions / Departments → Groups. Master data — rename, move or deactivate without losing history."
        extra={<Button leftSection={<IconPlus size={16} />} onClick={() => setSel({ parent_id: sel?.id, unit_type: 'DEPARTMENT', active: true })}>Add unit{sel?.code ? ` under ${sel.code}` : ''}</Button>} />
      <Grid>
        <Grid.Col span={{ base: 12, lg: 7 }}><Card p="sm">{(kids.root || []).map((o) => <Row key={o.id} o={o} depth={0} />)}</Card></Grid.Col>
        <Grid.Col span={{ base: 12, lg: 5 }}>{sel && <OrgForm key={sel.id || 'new' + sel.parent_id} unit={sel} all={data} onSaved={setSel} />}</Grid.Col>
      </Grid>
    </div>
  )
}

function OrgForm({ unit, all, onSaved }: { unit: any; all: any[]; onSaved: (u: any) => void }) {
  const [f, setF] = useState<any>({ code: '', name: '', description: '', is_oversight: false, active: true, ...unit })
  const isNew = !unit.id
  const save = useAction(() => (isNew ? api.post('/org-units', f) : api.put(`/org-units/${unit.id}`, f)), { success: 'Saved', invalidate: [['org-units']], onDone: (r: any) => onSaved({ ...f, ...r }) })
  const set = (k: string) => (v: any) => setF({ ...f, [k]: v })
  return (
    <Card>
      <Text fw={650} mb="sm">{isNew ? 'New organization unit' : `Edit ${unit.code}`}</Text>
      <Stack>
        <Group grow><TextInput label="Code" required value={f.code} onChange={(e) => set('code')(e.currentTarget.value.toUpperCase())} /><Select label="Type" value={f.unit_type} onChange={set('unit_type')} data={TYPES} /></Group>
        <TextInput label="Name" required value={f.name} onChange={(e) => set('name')(e.currentTarget.value)} />
        <Select label="Parent" clearable searchable value={f.parent_id || null} onChange={set('parent_id')} data={all.filter((o) => o.id !== unit.id).map((o) => ({ value: o.id, label: `${o.code} — ${o.name}` }))} />
        <Textarea label="Description" value={f.description || ''} onChange={(e) => set('description')(e.currentTarget.value)} />
        <Switch label="Central oversight (Head Directorate visibility of released documents)" checked={f.is_oversight} onChange={(e) => set('is_oversight')(e.currentTarget.checked)} />
        <Switch label="Active" checked={f.active} onChange={(e) => set('active')(e.currentTarget.checked)} />
        <Button loading={save.isPending} disabled={!f.code || f.name.length < 2} onClick={() => save.mutate(undefined)}>Save</Button>
      </Stack>
    </Card>
  )
}
