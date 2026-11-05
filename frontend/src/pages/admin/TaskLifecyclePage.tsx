import { ActionIcon, Alert, Badge, Button, Card, Checkbox, Group, MultiSelect, Select, SimpleGrid, Stack, Switch, Table, Text, TextInput } from '@mantine/core'
import { IconAlertTriangle, IconArrowRight, IconPlus, IconRoute, IconTrash } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import { useAction } from '../../api/hooks'
import { PageTitle } from '../../components/common'

const CATEGORY = [{ value: 'INITIAL', label: 'Initial' }, { value: 'ACTIVE', label: 'Active' }, { value: 'HOLD', label: 'On hold' }, { value: 'DONE', label: 'Done' }, { value: 'CANCELLED', label: 'Cancelled' }]
const ACTORS = [{ value: 'assignee', label: 'Owner' }, { value: 'reporter', label: 'Reporter' }, { value: 'reviewer', label: 'Reviewer' }, { value: 'manager', label: 'Task manager' }]
const RULES: Record<string, string> = {
  child_tasks_closed: 'All sub-tasks must be closed',
  mandatory_checklist: 'Mandatory checklist items must be ticked',
  mandatory_deliverables: 'Mandatory deliverable documents must reach their required status',
  predecessors: 'Dependencies must be satisfied (start and finish)',
}

export default function TaskLifecyclePage() {
  const q = useQuery<any>({ queryKey: ['task-lifecycle', null], queryFn: () => api.get('/task-lifecycle') })
  const [states, setStates] = useState<any[]>([])
  const [transitions, setTransitions] = useState<any[]>([])
  const [rules, setRules] = useState<Record<string, boolean>>({})
  useEffect(() => { if (q.data) { setStates(q.data.states); setTransitions(q.data.transitions); setRules(q.data.completion_rules) } }, [q.data])
  const save = useAction(() => api.put('/task-lifecycle', { states, transitions, completion_rules: rules }), { success: 'Task lifecycle saved', invalidate: [['task-lifecycle']] })
  const stateData = states.map((s) => ({ value: s.code, label: s.label || s.code }))
  const patchT = (i: number, p: any) => setTransitions((t) => t.map((x, n) => (n === i ? { ...x, ...p } : x)))
  const patchS = (i: number, p: any) => setStates((t) => t.map((x, n) => (n === i ? { ...x, ...p } : x)))
  return (
    <div className="page">
      <PageTitle icon={<IconRoute size={22} />} title="Task lifecycle" sub="The states a task moves through and who may move it. Enforced on the server for every project without its own lifecycle."
        extra={<><Button variant="default" onClick={() => { setStates(q.data.default.states); setTransitions(q.data.default.transitions) }}>Load default</Button><Button loading={save.isPending} onClick={() => save.mutate(undefined)}>Validate and save</Button></>} />
      <Alert color="blue" mb="md" p="xs" icon={<IconAlertTriangle size={16} />}>Saving checks that every state can be reached and can finish. A state that tasks are using cannot be removed.</Alert>
      <SimpleGrid cols={{ base: 1, xl: 2 }} mb="md">
        <Card withBorder>
          <Group justify="space-between" mb="sm"><Text fw={650}>States</Text><Button size="xs" variant="light" leftSection={<IconPlus size={14} />} onClick={() => setStates((s) => [...s, { code: '', label: '', category: 'ACTIVE', color: 'blue' }])}>State</Button></Group>
          <Table verticalSpacing={4}>
            <Table.Thead><Table.Tr><Table.Th>Code</Table.Th><Table.Th>Label</Table.Th><Table.Th>Meaning</Table.Th><Table.Th /></Table.Tr></Table.Thead>
            <Table.Tbody>{states.map((s, i) => (
              <Table.Tr key={i}>
                <Table.Td><TextInput size="xs" aria-label="State code" value={s.code} onChange={(e) => patchS(i, { code: e.currentTarget.value.toUpperCase().replace(/[^A-Z0-9_]/g, '_') })} /></Table.Td>
                <Table.Td><TextInput size="xs" aria-label="State label" value={s.label} onChange={(e) => patchS(i, { label: e.currentTarget.value })} /></Table.Td>
                <Table.Td><Select size="xs" aria-label="State meaning" allowDeselect={false} value={s.category} onChange={(v) => patchS(i, { category: v })} data={CATEGORY} /></Table.Td>
                <Table.Td><ActionIcon size="sm" variant="subtle" color="red" aria-label="Remove state" onClick={() => setStates((x) => x.filter((_, n) => n !== i))}><IconTrash size={14} /></ActionIcon></Table.Td>
              </Table.Tr>
            ))}</Table.Tbody>
          </Table>
        </Card>
        <Card withBorder>
          <Text fw={650} mb="sm">Before a task can be completed</Text>
          <Stack gap="sm">{Object.entries(RULES).map(([k, label]) => <Switch key={k} label={label} checked={!!rules[k]} onChange={(e) => { const on = e.currentTarget.checked; setRules((r) => ({ ...r, [k]: on })) }} />)}</Stack>
          <Text size="xs" c="dimmed" mt="md">These rules are shared by all projects.</Text>
        </Card>
      </SimpleGrid>
      <Card withBorder>
        <Group justify="space-between" mb="sm"><Group gap={8}><Text fw={650}>Allowed moves</Text><Badge variant="light">{transitions.length}</Badge></Group><Button size="xs" variant="light" leftSection={<IconPlus size={14} />} onClick={() => setTransitions((t) => [...t, { from: states[0]?.code, to: states[1]?.code, label: '', actors: ['manager'] }])}>Move</Button></Group>
        <div style={{ overflowX: 'auto' }}>
          <Table verticalSpacing={4} miw={880}>
            <Table.Thead><Table.Tr><Table.Th>From</Table.Th><Table.Th /><Table.Th>To</Table.Th><Table.Th>Button label</Table.Th><Table.Th>Who may do it</Table.Th><Table.Th>Reason</Table.Th><Table.Th /></Table.Tr></Table.Thead>
            <Table.Tbody>{transitions.map((t, i) => (
              <Table.Tr key={i}>
                <Table.Td w={170}><Select size="xs" aria-label="From state" allowDeselect={false} value={t.from} onChange={(v) => patchT(i, { from: v })} data={stateData} /></Table.Td>
                <Table.Td w={20}><IconArrowRight size={14} /></Table.Td>
                <Table.Td w={170}><Select size="xs" aria-label="To state" allowDeselect={false} value={t.to} onChange={(v) => patchT(i, { to: v })} data={stateData} /></Table.Td>
                <Table.Td><TextInput size="xs" aria-label="Button label" value={t.label || ''} onChange={(e) => patchT(i, { label: e.currentTarget.value })} /></Table.Td>
                <Table.Td><MultiSelect size="xs" aria-label="Who may do it" value={t.actors || []} onChange={(v) => patchT(i, { actors: v })} data={ACTORS} /></Table.Td>
                <Table.Td ta="center"><Checkbox aria-label="Reason required" checked={!!t.reason} onChange={(e) => patchT(i, { reason: e.currentTarget.checked })} /></Table.Td>
                <Table.Td w={36}><ActionIcon size="sm" variant="subtle" color="red" aria-label="Remove move" onClick={() => setTransitions((x) => x.filter((_, n) => n !== i))}><IconTrash size={14} /></ActionIcon></Table.Td>
              </Table.Tr>
            ))}</Table.Tbody>
          </Table>
        </div>
      </Card>
    </div>
  )
}
