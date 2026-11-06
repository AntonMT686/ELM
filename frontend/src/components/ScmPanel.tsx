import { ActionIcon, Alert, Anchor, Badge, Button, Group, Select, Stack, Table, Text, TextInput, Tooltip } from '@mantine/core'
import { IconAlertTriangle, IconBrandGitlab, IconExternalLink, IconGitBranch, IconGitCommit, IconGitMerge, IconGitPullRequest, IconRefresh, IconTrash } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { useAction } from '../api/hooks'
import { When } from './common'

const KIND_ICON: Record<string, JSX.Element> = { BRANCH: <IconGitBranch size={15} />, COMMIT: <IconGitCommit size={15} />, MERGE_REQUEST: <IconGitPullRequest size={15} /> }
const STATE_COLOR: Record<string, string> = { opened: 'blue', merged: 'teal', closed: 'gray', locked: 'orange', active: 'blue', deleted: 'gray' }

/** GitLab traceability for one task: branches, commits and merge requests, plus the operations ELM may perform. */
export default function ScmPanel({ task, keys }: { task: any; keys: any[][] }) {
  const q = useQuery<any>({ queryKey: ['work-item-scm', task.id], queryFn: () => api.get(`/work-items/${task.id}/scm`) })
  const allKeys = [['work-item-scm', task.id], ...keys]
  const [repo, setRepo] = useState<string | null>(null)
  const [branch, setBranch] = useState('')
  useEffect(() => { if (!repo && q.data?.repositories?.length) setRepo(q.data.repositories.find((r: any) => r.active)?.id || null) }, [q.data, repo])
  const r = q.data?.repositories?.find((x: any) => x.id === repo)
  useEffect(() => { if (r) setBranch(q.data.suggested_branch.replace('{prefix}', r.branch_prefix)) }, [r?.id])
  const mkBranch = useAction(() => api.post(`/work-items/${task.id}/scm/branch`, { repository_id: repo, name: branch || undefined }), { success: (x: any) => `Branch ${x.ref} created in GitLab`, invalidate: allKeys })
  const mkMr = useAction(() => api.post(`/work-items/${task.id}/scm/merge-request`, { repository_id: repo }), { success: (x: any) => `Merge request !${x.ref} opened`, invalidate: allKeys })
  const sync = useAction(() => api.post(`/work-items/${task.id}/scm/sync`), { success: (c: any) => `Synchronised: ${c.branches} branch(es), ${c.merge_requests} merge request(s), ${c.commits} commit(s) new`, invalidate: allKeys })
  const del = useAction((id: string) => api.del(`/work-items/${task.id}/scm/links/${id}`), { success: 'Link removed', invalidate: allKeys })

  if (q.isLoading || !q.data) return null
  const d = q.data
  if (!d.repositories.length)
    return <Alert color="gray" icon={<IconBrandGitlab size={16} />} title="No GitLab repository for this project">A project engineer can register one under <Anchor component={Link} to="/source-control">Source control</Anchor>. Until then, record work in the task history.</Alert>
  const hasBranch = d.links.some((l: any) => l.kind === 'BRANCH' && l.repository?.id === repo)
  return (
    <Stack>
      {!d.enabled && <Alert color="orange" icon={<IconAlertTriangle size={16} />}>GitLab is switched off or not configured on the server, so ELM can only show what it already knows.</Alert>}
      {d.can_operate && d.enabled && (
        <Stack gap="xs">
          <Group grow align="flex-end">
            <Select label="Repository" value={repo} onChange={setRepo} allowDeselect={false} data={d.repositories.filter((x: any) => x.active).map((x: any) => ({ value: x.id, label: x.path }))} />
            <TextInput label="Branch name" value={branch} onChange={(e) => setBranch(e.currentTarget.value)} description={`Must contain ${task.key}`} />
          </Group>
          <Group gap="xs">
            <Button size="xs" leftSection={<IconGitBranch size={14} />} disabled={!repo || hasBranch} loading={mkBranch.isPending} onClick={() => mkBranch.mutate(undefined)}>Create branch</Button>
            <Tooltip label="Create a branch first" disabled={hasBranch}><Button size="xs" variant="light" leftSection={<IconGitMerge size={14} />} disabled={!repo || !hasBranch} loading={mkMr.isPending} onClick={() => mkMr.mutate(undefined)}>Open merge request</Button></Tooltip>
            <Button size="xs" variant="default" leftSection={<IconRefresh size={14} />} loading={sync.isPending} onClick={() => sync.mutate(undefined)}>Sync from GitLab</Button>
          </Group>
          <Text size="xs" c="dimmed">Clone and commit with your usual Git tools. Put <b>{task.key}</b> in commit messages so ELM links them. Code-review approval is given here in ELM.</Text>
        </Stack>
      )}
      {!!d.blockers.length && <Alert color="orange" p="xs" icon={<IconAlertTriangle size={16} />} title="Before this task can be completed">{d.blockers.join(' · ')}</Alert>}
      <Table verticalSpacing={6} fz="sm">
        <Table.Tbody>
          {d.links.map((l: any) => (
            <Table.Tr key={l.id}>
              <Table.Td w={28}>{KIND_ICON[l.kind]}</Table.Td>
              <Table.Td>
                <Group gap={6} wrap="nowrap">
                  <Text size="sm" fw={600} ff={l.kind === 'COMMIT' ? 'monospace' : undefined}>{l.kind === 'MERGE_REQUEST' ? `!${l.ref}` : l.kind === 'COMMIT' ? l.ref.slice(0, 10) : l.ref}</Text>
                  {l.state && <Badge size="xs" color={STATE_COLOR[l.state] || 'gray'}>{l.state}</Badge>}
                  {l.origin === 'MANUAL' && <Badge size="xs" variant="outline" color="gray">manual</Badge>}
                </Group>
                {l.title && <Text size="xs" c="dimmed" lineClamp={1}>{l.title}{l.kind === 'MERGE_REQUEST' && l.source_branch ? ` (${l.source_branch} → ${l.target_branch})` : ''}</Text>}
              </Table.Td>
              <Table.Td><Text size="xs" c="dimmed">{l.author}</Text><When at={l.external_at || l.created_at} /></Table.Td>
              <Table.Td w={60}>
                <Group gap={2} wrap="nowrap">
                  {l.url && <ActionIcon component="a" href={l.url} target="_blank" rel="noreferrer" variant="subtle" size="sm"><IconExternalLink size={14} /></ActionIcon>}
                  {l.origin === 'MANUAL' && d.can_operate && <ActionIcon variant="subtle" color="red" size="sm" onClick={() => del.mutate(l.id)}><IconTrash size={14} /></ActionIcon>}
                </Group>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      {!d.links.length && <Text size="sm" c="dimmed">Nothing linked yet.</Text>}
      {d.operations.some((o: any) => o.status === 'FAILED') && (
        <Text size="xs" c="red">Last failed GitLab call: {d.operations.find((o: any) => o.status === 'FAILED').error}</Text>
      )}
    </Stack>
  )
}
