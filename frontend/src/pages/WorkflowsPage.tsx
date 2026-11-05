import { Badge, Button, Card, Group, Modal, Select, SimpleGrid, Stack, Text, TextInput, Textarea } from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { IconArrowRight, IconGitBranch, IconPlus } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useAction } from '../api/hooks'
import { PageTitle, When } from '../components/common'

export default function WorkflowsPage() {
  const nav = useNavigate()
  const { data = [] } = useQuery<any[]>({ queryKey: ['workflows'], queryFn: () => api.get('/workflow-definitions') })
  const [open, m] = useDisclosure(false)
  return (
    <div className="page">
      <PageTitle icon={<IconGitBranch size={22} />} title="Workflow designer" sub="Configure review, approval, signature and release flows without code. Published versions are immutable; running documents stay on their version."
        extra={<Button leftSection={<IconPlus size={16} />} onClick={m.open}>New workflow</Button>} />
      <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }}>
        {data.map((w) => (
          <Card key={w.id} className="clickable" onClick={() => nav(`/workflows/${w.id}`)}>
            <Group justify="space-between"><Badge color="gray" variant="outline">{w.code}</Badge>{w.latest_version ? <Badge color="teal">v{w.latest_version} published</Badge> : <Badge color="orange">Draft only</Badge>}</Group>
            <Text fw={650} size="lg" mt="sm">{w.name}</Text>
            <Text size="sm" c="dimmed" lineClamp={2} mih={40}>{w.description}</Text>
            <Group gap={4} mt="md" wrap="wrap">
              {w.stage_summary.map((s: string, i: number) => (
                <Group key={i} gap={4} wrap="nowrap"><Badge size="sm" variant="light">{s}</Badge>{i < w.stage_summary.length - 1 && <IconArrowRight size={12} color="#94a3b8" />}</Group>
              ))}
            </Group>
            <Group justify="space-between" mt="md">
              <Text size="xs" c="dimmed">{w.binding_count} binding(s) · {w.running_instances} running</Text>
              {w.has_unpublished_changes && <Badge size="xs" color="orange">unpublished changes</Badge>}
              <Text size="xs" c="dimmed">{w.published_at && <When at={w.published_at} />}</Text>
            </Group>
          </Card>
        ))}
      </SimpleGrid>
      <NewWorkflow opened={open} onClose={m.close} existing={data} />
    </div>
  )
}

function NewWorkflow({ opened, onClose, existing }: { opened: boolean; onClose: () => void; existing: any[] }) {
  const nav = useNavigate()
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [desc, setDesc] = useState('')
  const [copy, setCopy] = useState<string | null>(null)
  const act = useAction(() => api.post('/workflow-definitions', { code, name, description: desc, copy_from_id: copy }), { success: 'Workflow created', invalidate: [['workflows']], onDone: (r: any) => { onClose(); nav(`/workflows/${r.id}`) } })
  return (
    <Modal opened={opened} onClose={onClose} title="New workflow">
      <Stack>
        <TextInput label="Code" required value={code} onChange={(e) => setCode(e.currentTarget.value.toUpperCase().replace(/[^A-Z0-9_-]/g, ''))} placeholder="e.g. HW-QUAL-REVIEW" />
        <TextInput label="Name" required value={name} onChange={(e) => setName(e.currentTarget.value)} />
        <Textarea label="Purpose" value={desc} onChange={(e) => setDesc(e.currentTarget.value)} />
        <Select label="Start from a copy of" clearable value={copy} onChange={setCopy} data={existing.map((w) => ({ value: w.id, label: w.name }))} placeholder="Blank (Prepare → Approve)" />
        <Group justify="flex-end"><Button variant="default" onClick={onClose}>Cancel</Button><Button disabled={code.length < 3 || name.length < 3} loading={act.isPending} onClick={() => act.mutate(undefined)}>Create</Button></Group>
      </Stack>
    </Modal>
  )
}
