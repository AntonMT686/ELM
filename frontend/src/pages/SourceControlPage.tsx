import { Alert, Anchor, Badge, Button, Card, Code, Group, Modal, Select, Stack, Switch, Table, Text, TextInput } from '@mantine/core'
import { IconAlertTriangle, IconBrandGitlab, IconCheck, IconPlus } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { useAction, useProjects } from '../api/hooks'
import { EmptyBlock, PageTitle, When } from '../components/common'

/** GitLab repositories registered per project (the allow-list), connection status and webhook set-up (architecture §12.2–12.3). */
export default function SourceControlPage() {
  const projects = useProjects()
  const [project, setProject] = useState<string | null>(null)
  useEffect(() => { if (!project && projects.data?.length) setProject(projects.data[0].id) }, [projects.data, project])
  const status = useQuery<any>({ queryKey: ['scm-status'], queryFn: () => api.get('/scm/status', { check: true }), staleTime: 60_000 })
  const repos = useQuery<any>({ queryKey: ['repositories', project], queryFn: () => api.get(`/projects/${project}/repositories`), enabled: !!project })
  const events = useQuery<any[]>({ queryKey: ['scm-events', project], queryFn: () => api.get(`/projects/${project}/scm/webhook-events`), enabled: !!project && !!repos.data?.can_manage })
  const [adding, setAdding] = useState(false)
  const s = status.data
  const keys = [['repositories', project]]
  const toggle = useAction((r: any) => api.patch(`/repositories/${r.id}?version=${r.version}`, { active: !r.active }), { success: 'Repository updated', invalidate: keys })

  return (
    <div className="page">
      <PageTitle icon={<IconBrandGitlab size={22} />} title="Source control" sub="GitLab repositories each project may use. ELM creates task branches and merge requests in these repositories only, and links commits that mention a task key."
        extra={<>
          <Select w={180} value={project} onChange={setProject} allowDeselect={false} data={(projects.data || []).map((p) => ({ value: p.id, label: p.code }))} />
          {repos.data?.can_manage && <Button leftSection={<IconPlus size={16} />} disabled={!s?.enabled} onClick={() => setAdding(true)}>Register repository</Button>}
        </>} />
      {s && (
        <Card mb="md">
          <Group justify="space-between">
            <Group gap="xs">
              <Text fw={600}>GitLab server</Text>
              <Anchor href={s.url} target="_blank" size="sm">{s.url}</Anchor>
              {!s.enabled ? <Badge color="gray">switched off</Badge> : s.reachable ? <Badge color="teal" leftSection={<IconCheck size={12} />}>connected · {s.version}</Badge> : <Badge color="red">not reachable</Badge>}
            </Group>
          </Group>
          {s.enabled && !s.reachable && <Text size="sm" c="red" mt="xs">{s.error}</Text>}
          {!s.enabled && <Text size="sm" c="dimmed" mt="xs">Set ELM_GITLAB_ENABLED=true, ELM_GITLAB_URL and ELM_GITLAB_TOKEN in .env and restart the backend.</Text>}
          {s.enabled && (
            <Text size="sm" c="dimmed" mt="xs">
              Webhook for each registered GitLab project (Settings → Webhooks): URL <Code>{'<ELM backend URL reachable from GitLab>'}{s.webhook_url}</Code>, secret token = ELM_GITLAB_WEBHOOK_SECRET, triggers <b>Push events</b> and <b>Merge request events</b>.
              {!s.webhook_secret_set && <Text span c="orange"> No webhook secret is set on the server, so webhooks are refused.</Text>}
            </Text>
          )}
        </Card>
      )}
      <Card p={0}>
        <Table verticalSpacing="sm" highlightOnHover>
          <Table.Thead><Table.Tr><Table.Th>Repository</Table.Th><Table.Th>Default branch</Table.Th><Table.Th>Branch prefix</Table.Th><Table.Th>Last GitLab event</Table.Th><Table.Th>In use</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>
            {(repos.data?.items || []).map((r: any) => (
              <Table.Tr key={r.id}>
                <Table.Td><Anchor href={r.web_url} target="_blank" fw={600} size="sm">{r.path}</Anchor><Text size="xs" c="dimmed">GitLab id {r.external_id}</Text></Table.Td>
                <Table.Td><Code>{r.default_branch}</Code></Table.Td>
                <Table.Td><Code>{r.branch_prefix || '—'}</Code></Table.Td>
                <Table.Td>{r.last_event_at ? <When at={r.last_event_at} /> : <Text size="xs" c="dimmed">none yet</Text>}</Table.Td>
                <Table.Td><Switch checked={r.active} disabled={!repos.data?.can_manage} onChange={() => toggle.mutate(r)} /></Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        {!repos.data?.items?.length && <EmptyBlock text="No repository is registered for this project yet." />}
      </Card>
      {!!events.data?.length && (
        <Card mt="md">
          <Text fw={600} mb="xs">Recent webhook deliveries</Text>
          <Stack gap={4}>{events.data.map((e) => <Group key={e.id} gap="xs"><When at={e.received_at} /><Badge size="xs" color={e.status === 'PROCESSED' ? 'teal' : e.status === 'FAILED' ? 'red' : 'gray'}>{e.status}</Badge><Text size="sm">{e.event}</Text><Text size="xs" c="dimmed">{e.links_created} new link(s){e.note ? ` · ${e.note}` : ''}</Text></Group>)}</Stack>
        </Card>
      )}
      {project && <RegisterModal opened={adding} onClose={() => setAdding(false)} project={project} keys={keys} />}
    </div>
  )
}

function RegisterModal({ opened, onClose, project, keys }: { opened: boolean; onClose: () => void; project: string; keys: any[][] }) {
  const [path, setPath] = useState('')
  const [prefix, setPrefix] = useState('task/')
  const save = useAction(() => api.post(`/projects/${project}/repositories`, { path, branch_prefix: prefix }), { success: (r: any) => `${r.path} registered`, invalidate: keys, onDone: () => { setPath(''); onClose() } })
  return (
    <Modal opened={opened} onClose={onClose} title="Register a GitLab repository">
      <Stack>
        <TextInput label="GitLab project path" placeholder="group/project" required value={path} onChange={(e) => setPath(e.currentTarget.value)} description="As in the GitLab URL, or the numeric project id. ELM checks it with GitLab before saving." />
        <TextInput label="Branch prefix for task branches" value={prefix} onChange={(e) => setPrefix(e.currentTarget.value)} />
        <Alert color="blue" icon={<IconAlertTriangle size={16} />} p="xs">The server's GitLab token must have access to this project.</Alert>
        <Group justify="flex-end"><Button variant="default" onClick={onClose}>Cancel</Button><Button disabled={!path.trim()} loading={save.isPending} onClick={() => save.mutate(undefined)}>Register</Button></Group>
      </Stack>
    </Modal>
  )
}
