import { Alert, Anchor, Badge, Button, Card, Group, Menu, NumberInput, Select, SimpleGrid, Stack, Table, Tabs, Text } from '@mantine/core'
import { IconBinaryTree, IconGitBranch, IconHierarchy3, IconPlus } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import { Background, Controls, MarkerType, ReactFlow, type Edge, type Node } from '@xyflow/react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { useAction, useProjects } from '../api/hooks'
import { EmptyBlock, PageTitle } from '../components/common'

export const TRACE_TYPES: Record<string, { label: string; color: string }> = {
  DOCUMENT: { label: 'Documents', color: '#7c3aed' }, REQUIREMENT: { label: 'Requirements', color: '#2563eb' }, DESIGN: { label: 'Design', color: '#4f46e5' },
  TASK: { label: 'Tasks / development', color: '#0891b2' }, CODE: { label: 'Code (GitLab)', color: '#475569' }, TEST_CASE: { label: 'Test cases', color: '#0d9488' },
  TEST_RUN: { label: 'Test runs', color: '#16a34a' }, DEFECT: { label: 'Defects', color: '#dc2626' }, DEPLOYMENT: { label: 'Deployments', color: '#ea580c' },
}
const ORDER = Object.keys(TRACE_TYPES)

/** "Trace" button for any record: opens the end-to-end trace starting there. */
export function TraceButton({ type, id, size = 'xs' }: { type: string; id: string; size?: string }) {
  return <Button size={size} variant="default" leftSection={<IconHierarchy3 size={14} />} component={Link} to={`/trace?type=${type}&id=${id}`}>Trace</Button>
}

/** "Start activity" from a requirement: creates the design record / task / test case and links it. */
export function DeriveMenu({ requirementId }: { requirementId: string }) {
  const nav = useNavigate()
  const go = useAction((kind: string) => api.post(`/requirements/${requirementId}/derive`, { kind }), { success: (r: any) => `${r.key} created and linked`, invalidate: [['requirement', requirementId], ['rtm']], onDone: (r: any) => nav(r.route) })
  return (
    <Menu shadow="md" position="bottom-end">
      <Menu.Target><Button size="xs" variant="light" leftSection={<IconPlus size={14} />} loading={go.isPending}>Start activity</Button></Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>Create from this requirement and link it</Menu.Label>
        <Menu.Item onClick={() => go.mutate('DESIGN')}>Design record (satisfies)</Menu.Item>
        <Menu.Item onClick={() => go.mutate('DEVELOPMENT')}>Development task (implements, GitLab)</Menu.Item>
        <Menu.Item onClick={() => go.mutate('TASK')}>Task (implements)</Menu.Item>
        <Menu.Item onClick={() => go.mutate('TEST_CASE')}>Test case (verifies)</Menu.Item>
      </Menu.Dropdown>
    </Menu>
  )
}

export default function TracePage() {
  const [sp, setSp] = useSearchParams()
  const type = sp.get('type')
  const id = sp.get('id')
  const [depth, setDepth] = useState<number>(4)
  const q = useQuery<any>({ queryKey: ['trace', type, id, depth], queryFn: () => api.get('/trace', { type, id, depth }), enabled: !!type && !!id })
  const nav = useNavigate()
  const g = q.data
  const root = g?.nodes.find((n: any) => n.root)
  const { nodes, edges } = useMemo(() => layout(g), [g])
  return (
    <div className="page" style={{ maxWidth: 1900 }}>
      <PageTitle icon={<IconBinaryTree size={22} />} title="Traceability" sub="Everything linked to a record: documents, requirements, design, development and code, tests, runs, defects and deployments."
        extra={<Group><Text size="sm">Depth</Text><NumberInput w={80} min={1} max={8} value={depth} onChange={(v) => setDepth(Number(v) || 4)} /></Group>} />
      <Picker onPick={(t, i) => setSp({ type: t, id: i })} />
      {!type || !id ? <EmptyBlock text="Choose where to start: a requirement, a document, a design record, a test case, a defect or a deployment. Every record also has a Trace button." /> : !g ? null : !g.nodes.length ? <Alert color="red">You cannot open this record.</Alert> : (
        <Tabs defaultValue="graph" mt="md">
          <Tabs.List>
            <Tabs.Tab value="graph">Graph</Tabs.Tab>
            <Tabs.Tab value="list">List</Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="graph" pt="sm">
            <Group gap={6} mb="xs">{ORDER.filter((t) => g.counts[t]).map((t) => <Badge key={t} variant="light" style={{ background: TRACE_TYPES[t].color + '22', color: TRACE_TYPES[t].color }}>{TRACE_TYPES[t].label}: {g.counts[t]}</Badge>)}{g.truncated && <Badge color="orange">limited to 250 records</Badge>}</Group>
            <Card withBorder p={0} style={{ height: '68vh' }}>
              <ReactFlow nodes={nodes} edges={edges} fitView nodesDraggable onNodeClick={(_, n: any) => { const x = n.data.raw; if (x.url) window.open(x.url, '_blank'); else if (x.route) nav(x.route) }} minZoom={0.2}>
                <Background /><Controls />
              </ReactFlow>
            </Card>
            <Text size="xs" c="dimmed" mt={4}>Start: {root?.key} {root?.title}. Click a box to open the record. Columns follow the lifecycle from documents to deployment.</Text>
          </Tabs.Panel>
          <Tabs.Panel value="list" pt="sm">
            <Table verticalSpacing={4} fz="sm">
              <Table.Thead><Table.Tr><Table.Th>Type</Table.Th><Table.Th>Record</Table.Th><Table.Th>Title</Table.Th><Table.Th>Status</Table.Th><Table.Th>Steps away</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>{g.nodes.map((n: any) => <Table.Tr key={n.id}><Table.Td><Text size="xs" c={TRACE_TYPES[n.type].color} fw={600}>{TRACE_TYPES[n.type].label}</Text></Table.Td><Table.Td>{n.url ? <Anchor size="sm" href={n.url} target="_blank">{n.key}</Anchor> : <Anchor size="sm" component={Link} to={n.route}>{n.key}</Anchor>}</Table.Td><Table.Td><Text size="sm" lineClamp={1}>{n.title}</Text></Table.Td><Table.Td><Badge size="xs" variant="light" color="gray">{String(n.status).replace(/_/g, ' ').toLowerCase()}</Badge></Table.Td><Table.Td>{n.depth}</Table.Td></Table.Tr>)}</Table.Tbody>
            </Table>
          </Tabs.Panel>
        </Tabs>
      )}
    </div>
  )
}

function layout(g: any): { nodes: Node[]; edges: Edge[] } {
  if (!g) return { nodes: [], edges: [] }
  const cols: Record<string, number> = {}
  const nodes: Node[] = g.nodes.map((n: any) => {
    const col = ORDER.indexOf(n.type)
    const row = (cols[n.type] = (cols[n.type] ?? -1) + 1)
    const c = TRACE_TYPES[n.type].color
    return {
      id: n.id, position: { x: col * 250, y: row * 92 }, data: { raw: n, label: (
        <div style={{ textAlign: 'left' }}>
          <div style={{ fontSize: 10, color: c, fontWeight: 700, textTransform: 'uppercase' }}>{TRACE_TYPES[n.type].label}</div>
          <div style={{ fontSize: 12, fontWeight: 700 }}>{n.key}</div>
          <div style={{ fontSize: 11, color: '#555', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 190 }}>{n.title}</div>
          <div style={{ fontSize: 10, color: '#777' }}>{String(n.status || '').replace(/_/g, ' ').toLowerCase()}</div>
        </div>) },
      style: { width: 215, border: `${n.root ? 3 : 1}px solid ${c}`, borderRadius: 8, padding: 6, background: 'var(--mantine-color-body)', cursor: 'pointer' },
    }
  })
  const edges: Edge[] = g.edges.map((e: any, i: number) => ({ id: `e${i}`, source: e.from, target: e.to, label: e.label, labelStyle: { fontSize: 9 }, markerEnd: { type: MarkerType.ArrowClosed }, style: { stroke: '#94a3b8' } }))
  return { nodes, edges }
}

function Picker({ onPick }: { onPick: (type: string, id: string) => void }) {
  const projects = useProjects()
  const [project, setProject] = useState<string | null>(null)
  const [type, setType] = useState<string>('REQUIREMENT')
  const [rec, setRec] = useState<string | null>(null)
  useEffect(() => { if (!project && projects.data?.length) setProject(projects.data[0].id) }, [projects.data, project])
  const url: Record<string, string> = { REQUIREMENT: `/projects/${project}/requirements`, DOCUMENT: '/documents', DESIGN: `/projects/${project}/designs`, TEST_CASE: `/projects/${project}/test-cases`, DEFECT: `/projects/${project}/defects`, DEPLOYMENT: `/projects/${project}/deployments`, TASK: '/work-items' }
  const params: any = type === 'DOCUMENT' ? { project_id: project, page_size: 200 } : type === 'TASK' ? { project_id: project } : undefined
  const list = useQuery<any>({ queryKey: ['trace-pick', project, type], queryFn: () => api.get(url[type], params), enabled: !!project })
  const rows = (Array.isArray(list.data) ? list.data : list.data?.items) || []
  return (
    <Card withBorder>
      <SimpleGrid cols={{ base: 1, md: 4 }}>
        <Select label="Project" value={project} onChange={(v) => { setProject(v); setRec(null) }} allowDeselect={false} data={(projects.data || []).map((p) => ({ value: p.id, label: p.code }))} />
        <Select label="Start from" value={type} onChange={(v) => { setType(v!); setRec(null) }} allowDeselect={false} data={['REQUIREMENT', 'DOCUMENT', 'DESIGN', 'TASK', 'TEST_CASE', 'DEFECT', 'DEPLOYMENT'].map((t) => ({ value: t, label: TRACE_TYPES[t].label }))} />
        <Select label="Record" searchable value={rec} onChange={setRec} data={rows.map((r: any) => ({ value: r.id, label: `${r.key || r.number} ${r.title}` }))} />
        <Stack justify="flex-end"><Button leftSection={<IconGitBranch size={16} />} disabled={!rec} onClick={() => rec && onPick(type, rec)}>Show trace</Button></Stack>
      </SimpleGrid>
    </Card>
  )
}
