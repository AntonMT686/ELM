import { ActionIcon, Badge, Button, Card, ColorInput, Group, Modal, MultiSelect, Select, SimpleGrid, Stack, Text, TextInput, Textarea } from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { IconAffiliate, IconArrowRight, IconPlus, IconTrash } from '@tabler/icons-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../api/client'
import { useAction, useOrgUnits, useProjects } from '../../api/hooks'
import { LevelTag, PageTitle } from '../../components/common'

export default function ProjectsPage() {
  const { data = [] } = useProjects()
  const nav = useNavigate()
  const [open, m] = useDisclosure(false)
  return (
    <div className="page">
      <PageTitle icon={<IconAffiliate size={22} />} title="Projects & product breakdown" sub="Each programme defines its own breakdown levels — e.g. Product → System → Subsystem → Unit, or Product → Unit → Component."
        extra={<Button leftSection={<IconPlus size={16} />} onClick={m.open}>New project</Button>} />
      <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }}>
        {data.map((p) => (
          <Card key={p.id}>
            <Group justify="space-between"><Group gap={8}><span style={{ width: 12, height: 12, borderRadius: 4, background: p.color || '#2563eb' }} /><Text fw={700} size="lg">{p.code}</Text></Group><Badge color={p.status === 'ACTIVE' ? 'teal' : 'gray'}>{p.status}</Badge></Group>
            <Text size="sm">{p.name}</Text><Text size="xs" c="dimmed">{p.programme}</Text>
            <Group gap={4} mt="md">{p.levels.map((l, i) => <Group key={l.id} gap={4}><LevelTag level={l.code} color={l.color} />{i < p.levels.length - 1 && <IconArrowRight size={12} color="#94a3b8" />}</Group>)}</Group>
            <Group gap={4} mt="sm">{p.orgs.map((o) => <Badge key={o.id} size="xs" color={o.participation === 'LEAD' ? 'blue' : 'gray'}>{o.code} · {o.participation.toLowerCase()}</Badge>)}</Group>
            <Group justify="space-between" mt="md"><Text size="xs" c="dimmed">{p.item_count} items · {Object.values(p.doc_counts || {}).reduce((a: number, b: any) => a + b, 0)} documents</Text><Button size="xs" variant="light" onClick={() => nav(`/explorer/${p.id}`)}>Open structure</Button></Group>
          </Card>
        ))}
      </SimpleGrid>
      <NewProject opened={open} onClose={m.close} />
    </div>
  )
}

function NewProject({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const orgs = useOrgUnits()
  const [f, setF] = useState<any>({ code: '', name: '', programme: '', description: '', color: '#2563eb', lead_org_unit_id: null, contributing_org_ids: [] })
  const [levels, setLevels] = useState([{ code: 'PRODUCT', name: 'Product' }, { code: 'SYSTEM', name: 'System' }, { code: 'SUBSYSTEM', name: 'Subsystem' }, { code: 'UNIT', name: 'Unit' }])
  const act = useAction(() => api.post('/projects', { ...f, levels }), { success: 'Project created', invalidate: [['projects'], ['me']], onDone: onClose })
  const set = (k: string) => (v: any) => setF({ ...f, [k]: v })
  const orgData = (orgs.data || []).map((o) => ({ value: o.id, label: `${o.code} — ${o.name}` }))
  return (
    <Modal opened={opened} onClose={onClose} size={640} title="New project / programme">
      <Stack>
        <Group grow><TextInput label="Code" required value={f.code} onChange={(e) => set('code')(e.currentTarget.value.toUpperCase())} /><ColorInput label="Colour" value={f.color} onChange={set('color')} /></Group>
        <TextInput label="Name" required value={f.name} onChange={(e) => set('name')(e.currentTarget.value)} />
        <TextInput label="Programme" value={f.programme} onChange={(e) => set('programme')(e.currentTarget.value)} />
        <Textarea label="Description" value={f.description} onChange={(e) => set('description')(e.currentTarget.value)} />
        <Group grow><Select label="Lead directorate" searchable value={f.lead_org_unit_id} onChange={set('lead_org_unit_id')} data={orgData} /><MultiSelect label="Contributing directorates" searchable value={f.contributing_org_ids} onChange={set('contributing_org_ids')} data={orgData} /></Group>
        <Text fw={600} size="sm">Breakdown levels (top → bottom)</Text>
        {levels.map((l, i) => (
          <Group key={i} grow>
            <TextInput size="xs" value={l.code} onChange={(e) => setLevels(levels.map((x, j) => (j === i ? { ...x, code: e.currentTarget.value.toUpperCase() } : x)))} />
            <TextInput size="xs" value={l.name} onChange={(e) => setLevels(levels.map((x, j) => (j === i ? { ...x, name: e.currentTarget.value } : x)))} />
            <ActionIcon style={{ flex: 'none' }} color="red" variant="subtle" disabled={levels.length < 2} onClick={() => setLevels(levels.filter((_, j) => j !== i))}><IconTrash size={14} /></ActionIcon>
          </Group>
        ))}
        <Button variant="subtle" size="xs" leftSection={<IconPlus size={14} />} onClick={() => setLevels([...levels, { code: 'LEVEL' + (levels.length + 1), name: 'Level ' + (levels.length + 1) }])}>Add level</Button>
        <Group justify="flex-end"><Button variant="default" onClick={onClose}>Cancel</Button><Button disabled={f.code.length < 2 || f.name.length < 2} loading={act.isPending} onClick={() => act.mutate(undefined)}>Create project</Button></Group>
      </Stack>
    </Modal>
  )
}
