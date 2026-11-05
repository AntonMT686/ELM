import { Badge, Breadcrumbs, Button, Card, Grid, Group, Modal, Progress, RingProgress, ScrollArea, Select, SimpleGrid, Stack, Table, Tabs, Text, TextInput, Title, Tooltip } from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { IconBinaryTree2, IconChevronDown, IconChevronRight, IconFilePlus, IconPlus, IconSearch } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { useAction, useMe, useOrgUnits } from '../api/hooks'
import type { DocBrief, TreeItem } from '../api/types'
import { EmptyBlock, LevelTag, PageTitle, StatusTag, TypeBadge, UserAvatar, When } from '../components/common'
import NewDocumentModal from '../components/NewDocumentModal'

const SEG: [string, string][] = [['RELEASED', 'teal'], ['APPROVED', 'cyan'], ['IN_REVIEW', 'blue'], ['CHANGES_REQUESTED', 'orange'], ['DRAFT', 'gray']]

export default function ExplorerPage() {
  const { data: me } = useMe()
  const params = useParams()
  const nav = useNavigate()
  const [sp, setSp] = useSearchParams()
  const projectId = params.projectId || me?.projects[0]?.id
  const { data, isLoading } = useQuery<{ project: any; items: TreeItem[] }>({ queryKey: ['tree', projectId], queryFn: () => api.get(`/projects/${projectId}/tree`), enabled: !!projectId })
  const [filter, setFilter] = useState('')
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const selected = sp.get('item') || data?.items.find((i) => !i.parent_id)?.id
  const byParent = useMemo(() => {
    const m: Record<string, TreeItem[]> = {}
    data?.items.forEach((i) => { (m[i.parent_id || 'root'] ||= []).push(i) })
    return m
  }, [data])

  // auto-expand ancestors of the selection and first two levels
  useEffect(() => {
    if (!data) return
    const o: Record<string, boolean> = {}
    data.items.forEach((i) => { if (i.level.no <= 2) o[i.id] = true })
    let cur = data.items.find((i) => i.id === selected)
    while (cur?.parent_id) { o[cur.parent_id] = true; cur = data.items.find((i) => i.id === cur!.parent_id) }
    setOpen((p) => ({ ...o, ...p }))
  }, [data, selected])

  const match = (i: TreeItem): boolean => !filter || `${i.code} ${i.name} ${i.part_number || ''}`.toLowerCase().includes(filter.toLowerCase()) || (byParent[i.id] || []).some(match)
  const Node = ({ it, depth }: { it: TreeItem; depth: number }) => {
    if (!match(it)) return null
    const kids = byParent[it.id] || []
    const isOpen = open[it.id] || !!filter
    return (
      <>
        <div className={`tree-row ${selected === it.id ? 'sel' : ''}`} style={{ paddingLeft: 6 + depth * 16 }} onClick={() => setSp({ item: it.id })}>
          <span style={{ width: 18, display: 'inline-flex' }} onClick={(e) => { e.stopPropagation(); setOpen({ ...open, [it.id]: !isOpen }) }}>
            {kids.length ? (isOpen ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />) : null}
          </span>
          <LevelTag level={it.level.code} color={it.level.color} />
          <span className="tree-node"><span className="code">{it.code}</span><span className="name">{it.name}</span></span>
          <Tooltip label={`${it.rollup.progress}% · ${it.rollup.released}/${it.rollup.total} released`}>
            <span className="mini-bar"><span style={{ width: `${it.rollup.progress}%` }} /></span>
          </Tooltip>
          <Text size="xs" c="dimmed" w={22} ta="right">{it.rollup.total || ''}</Text>
        </div>
        {isOpen && kids.map((k) => <Node key={k.id} it={k} depth={depth + 1} />)}
      </>
    )
  }

  if (!projectId) return <div className="page"><EmptyBlock text="You are not assigned to any project yet." /></div>
  return (
    <div className="page" style={{ maxWidth: 1800 }}>
      <PageTitle icon={<IconBinaryTree2 size={22} />} title="Product structure" sub="Navigate Aircraft → System → Subsystem → LRU and see every controlled document at each level."
        extra={<Select w={300} value={projectId} onChange={(v) => v && nav(`/explorer/${v}`)} data={(me?.projects || []).map((p) => ({ value: p.id, label: `${p.code} — ${p.name}` }))} />} />
      <Grid gutter="md">
        <Grid.Col span={{ base: 12, lg: 4.5, xl: 3.8 }}>
          <Card p="sm" style={{ position: 'sticky', top: 76 }}>
            <TextInput leftSection={<IconSearch size={16} />} placeholder="Filter by code, name, part no." value={filter} onChange={(e) => setFilter(e.currentTarget.value)} mb="xs" />
            <Group gap={6} mb={8}>{data?.project.levels.map((l: any) => <LevelTag key={l.id} level={l.code} color={l.color} />)}</Group>
            <ScrollArea h="calc(100vh - 290px)">
              {isLoading ? <Text c="dimmed" p="md">Loading structure…</Text> : (byParent.root || []).map((r) => <Node key={r.id} it={r} depth={0} />)}
            </ScrollArea>
          </Card>
        </Grid.Col>
        <Grid.Col span={{ base: 12, lg: 7.5, xl: 8.2 }}>
          {selected && data ? <ItemPanel key={selected} itemId={selected} tree={data.items} byParent={byParent} projectId={projectId} onSelect={(id) => setSp({ item: id })} /> : <Card><EmptyBlock text="Select an item from the structure" /></Card>}
        </Grid.Col>
      </Grid>
    </div>
  )
}

function ItemPanel({ itemId, tree, byParent, projectId, onSelect }: { itemId: string; tree: TreeItem[]; byParent: Record<string, TreeItem[]>; projectId: string; onSelect: (id: string) => void }) {
  const nav = useNavigate()
  const node = tree.find((i) => i.id === itemId)!
  const { data: item } = useQuery({ queryKey: ['item', itemId], queryFn: () => api.get(`/items/${itemId}`) })
  const [subtree, setSubtree] = useState(true)
  const docs = useQuery<{ items: DocBrief[]; total: number }>({ queryKey: ['documents', 'item', itemId, subtree], queryFn: () => api.get('/documents', { item_id: itemId, subtree, page_size: 100 }) })
  const [newDoc, nd] = useDisclosure(false)
  const [addOpen, add] = useDisclosure(false)
  const r = node?.rollup
  const kids = byParent[itemId] || []
  if (!node) return null
  return (
    <Stack gap="md">
      <Card>
        <Breadcrumbs separator="›" mb={8}>
          {(item?.breadcrumb || []).map((b: any) => <Text key={b.id} size="xs" c={b.id === itemId ? undefined : 'dimmed'} className="clickable" onClick={() => onSelect(b.id)}>{b.code}</Text>)}
        </Breadcrumbs>
        <Group justify="space-between" align="flex-start" wrap="wrap">
          <div>
            <Group gap={8}><LevelTag level={node.level.code} color={node.level.color} /><Title order={3}>{node.code}</Title>{node.part_number && <Badge color="gray" variant="outline">P/N {node.part_number}</Badge>}</Group>
            <Text size="lg" mt={2}>{node.name}</Text>
            <Group gap={8} mt={8}>
              <Badge color="violet">{node.lifecycle_phase.replace(/_/g, ' ')}</Badge>
              {item?.lead_org && <Badge color="blue">Lead: {item.lead_org.code}</Badge>}
              {item?.contributors?.map((c: any) => <Badge key={c.id} color="gray">{c.code}</Badge>)}
              {item?.domain && <Badge color="cyan">{item.domain.name}</Badge>}
              {item?.technical_owner && <Group gap={4}><UserAvatar user={item.technical_owner} size={20} /><Text size="xs" c="dimmed">Technical owner</Text></Group>}
            </Group>
          </div>
          <Group>
            {item?.can_manage && <Button variant="default" leftSection={<IconPlus size={16} />} onClick={add.open}>Add sub-item</Button>}
            <Button leftSection={<IconFilePlus size={16} />} onClick={nd.open}>New document here</Button>
          </Group>
        </Group>
        <SimpleGrid cols={{ base: 2, md: 4 }} mt="lg">
          <Group gap={12} wrap="nowrap">
            <RingProgress size={78} thickness={8} roundCaps sections={[{ value: r.progress, color: 'teal' }]} label={<Text ta="center" fw={700} size="sm">{r.progress}%</Text>} />
            <div><Text size="xs" c="dimmed">Subtree progress</Text><Text fw={600}>{r.released}/{r.total} released</Text></div>
          </Group>
          <div style={{ gridColumn: 'span 3' }}>
            <Text size="xs" c="dimmed" mb={6}>Documents by lifecycle state (this item and everything below)</Text>
            <Progress.Root size={22} radius="md">
              {SEG.map(([s, c]) => r.counts[s] ? (
                <Tooltip key={s} label={`${s.replace('_', ' ').toLowerCase()}: ${r.counts[s]}`}><Progress.Section value={(r.counts[s] / Math.max(1, r.total)) * 100} color={c}><Progress.Label>{r.counts[s]}</Progress.Label></Progress.Section></Tooltip>
              ) : null)}
            </Progress.Root>
            <Group gap={12} mt={8}>{SEG.map(([s, c]) => <Group key={s} gap={4}><span style={{ width: 9, height: 9, borderRadius: 3, background: `var(--mantine-color-${c}-6)` }} /><Text size="xs" c="dimmed">{s.replace('_', ' ').toLowerCase()}</Text></Group>)}</Group>
          </div>
        </SimpleGrid>
      </Card>

      <Card p={0}>
        <Tabs defaultValue="docs">
          <Tabs.List px="md" pt={6}>
            <Tabs.Tab value="docs">Documents ({docs.data?.total ?? '…'})</Tabs.Tab>
            <Tabs.Tab value="children">Sub-items ({kids.length})</Tabs.Tab>
            <Tabs.Tab value="tasks">Open tasks ({item?.open_tasks?.length ?? 0})</Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="docs" p="md">
            <Group justify="flex-end" mb="xs"><Button size="xs" variant={subtree ? 'light' : 'default'} onClick={() => setSubtree(!subtree)}>{subtree ? 'Including sub-items' : 'This item only'}</Button></Group>
            {!docs.data?.items.length ? <EmptyBlock text="No documents at this level yet." action={<Button size="xs" onClick={nd.open}>Create the first one</Button>} /> : (
              <Table>
                <Table.Thead><Table.Tr><Table.Th>Number</Table.Th><Table.Th>Title</Table.Th><Table.Th>Item</Table.Th><Table.Th>Rev</Table.Th><Table.Th>Status</Table.Th><Table.Th>Owner</Table.Th><Table.Th>Updated</Table.Th></Table.Tr></Table.Thead>
                <Table.Tbody>
                  {docs.data.items.map((d) => (
                    <Table.Tr key={d.id} className="clickable" onClick={() => nav(`/documents/${d.id}`)}>
                      <Table.Td><Group gap={6} wrap="nowrap"><TypeBadge type={d.type} /><Text size="sm" fw={600}>{d.number}</Text></Group></Table.Td>
                      <Table.Td><Text size="sm" lineClamp={1}>{d.title}</Text></Table.Td>
                      <Table.Td><Text size="xs" c="dimmed">{d.item?.code}</Text></Table.Td>
                      <Table.Td><Badge color="gray">{d.current_revision?.label}</Badge></Table.Td>
                      <Table.Td><StatusTag status={d.status} /></Table.Td>
                      <Table.Td><UserAvatar user={d.owner} size={24} /></Table.Td>
                      <Table.Td><Text size="xs" c="dimmed"><When at={d.updated_at} /></Text></Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            )}
          </Tabs.Panel>
          <Tabs.Panel value="children" p="md">
            {!kids.length ? <EmptyBlock text="No sub-items." /> : (
              <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }}>
                {kids.map((k) => (
                  <div key={k.id} className="kpi" style={{ padding: 14 }} onClick={() => onSelect(k.id)}>
                    <Group gap={6}><LevelTag level={k.level.code} color={k.level.color} /><Text fw={650} size="sm">{k.code}</Text></Group>
                    <Text size="sm" c="dimmed" lineClamp={1} mt={4}>{k.name}</Text>
                    <Progress value={k.rollup.progress} mt={10} size="sm" color="teal" />
                    <Text size="xs" c="dimmed" mt={4}>{k.rollup.progress}% · {k.rollup.total} documents · {k.lead_org?.code}</Text>
                  </div>
                ))}
              </SimpleGrid>
            )}
          </Tabs.Panel>
          <Tabs.Panel value="tasks" p="md">
            {!item?.open_tasks?.length ? <EmptyBlock text="No open tasks on this item." /> : (
              <Stack gap={4}>{item.open_tasks.map((t: any) => (
                <Group key={t.id} justify="space-between" className="inbox-item" onClick={() => nav(`/tasks?open=${t.id}`)}>
                  <Group gap={8}><Badge color="gray">{t.key}</Badge><Text size="sm">{t.title}</Text></Group>
                  <Group gap={8}><StatusTag status={t.status} /><UserAvatar user={t.assignee} size={22} /><Text size="xs" c="dimmed">{t.due_date}</Text></Group>
                </Group>
              ))}</Stack>
            )}
          </Tabs.Panel>
        </Tabs>
      </Card>
      <NewDocumentModal opened={newDoc} onClose={nd.close} projectId={projectId} itemId={itemId} />
      <AddItemModal opened={addOpen} onClose={add.close} projectId={projectId} parent={node} />
    </Stack>
  )
}

function AddItemModal({ opened, onClose, projectId, parent }: { opened: boolean; onClose: () => void; projectId: string; parent: TreeItem }) {
  const orgs = useOrgUnits()
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [pn, setPn] = useState('')
  const [lead, setLead] = useState<string | null>(null)
  const act = useAction(() => api.post(`/projects/${projectId}/items`, { parent_id: parent.id, code, name, part_number: pn || undefined, lead_org_unit_id: lead }), {
    success: 'Item added to the structure', invalidate: [['tree', projectId]], onDone: () => { setCode(''); setName(''); setPn(''); onClose() },
  })
  return (
    <Modal opened={opened} onClose={onClose} title={`Add item under ${parent.code}`}>
      <Stack>
        <Text size="sm" c="dimmed">The breakdown level is chosen automatically (next level below {parent.level.name}).</Text>
        <TextInput label="Code" required value={code} onChange={(e) => setCode(e.currentTarget.value.toUpperCase())} placeholder={`${parent.code}-XXX`} />
        <TextInput label="Name" required value={name} onChange={(e) => setName(e.currentTarget.value)} />
        <TextInput label="Part number" value={pn} onChange={(e) => setPn(e.currentTarget.value)} />
        <Select label="Lead directorate / department" clearable searchable value={lead} onChange={setLead} placeholder="Inherit from parent" data={(orgs.data || []).map((o) => ({ value: o.id, label: `${o.code} — ${o.name}` }))} />
        <Group justify="flex-end"><Button variant="default" onClick={onClose}>Cancel</Button><Button disabled={!code || name.length < 2} loading={act.isPending} onClick={() => act.mutate(undefined)}>Add item</Button></Group>
      </Stack>
    </Modal>
  )
}


