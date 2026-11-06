import { ActionIcon, Badge, Button, Group, Select, Stack, Table, Text, TextInput } from '@mantine/core'
import { IconExternalLink, IconGitBranch, IconGitCommit, IconGitPullRequest } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import { useAction } from '../api/hooks'
import { When } from './common'

const ICON: Record<string, JSX.Element> = { BRANCH: <IconGitBranch size={15} />, COMMIT: <IconGitCommit size={15} />, MERGE_REQUEST: <IconGitPullRequest size={15} /> }

/** GitLab links of a design record, test case or defect: found by its key in commits / branches / MRs, or added by hand. */
export default function ArtifactCode({ type, id }: { type: 'DESIGN' | 'TEST_CASE' | 'DEFECT'; id: string }) {
  const q = useQuery<any>({ queryKey: ['artifact-scm', type, id], queryFn: () => api.get(`/artifacts/${type}/${id}/scm`) })
  const [f, setF] = useState<any>({ repository_id: null, kind: 'COMMIT', ref: '', title: '' })
  const add = useAction(() => api.post(`/artifacts/${type}/${id}/scm`, { ...f, title: f.title || null }), { success: 'Linked', invalidate: [['artifact-scm', type, id]], onDone: () => setF({ ...f, ref: '', title: '' }) })
  if (!q.data) return null
  const d = q.data
  return (
    <Stack>
      <Text size="sm" c="dimmed">{d.hint}</Text>
      <Table verticalSpacing={4} fz="sm">
        <Table.Tbody>
          {d.links.map((l: any) => (
            <Table.Tr key={l.id}>
              <Table.Td w={24}>{ICON[l.kind]}</Table.Td>
              <Table.Td><Group gap={6}><Text size="sm" fw={600} ff={l.kind === 'COMMIT' ? 'monospace' : undefined}>{l.kind === 'MERGE_REQUEST' ? `!${l.ref}` : l.kind === 'COMMIT' ? l.ref.slice(0, 10) : l.ref}</Text>{l.state && <Badge size="xs">{l.state}</Badge>}{l.origin === 'MANUAL' && <Badge size="xs" variant="outline" color="gray">manual</Badge>}</Group>{l.title && <Text size="xs" c="dimmed" lineClamp={1}>{l.title}</Text>}</Table.Td>
              <Table.Td><Text size="xs" c="dimmed">{l.repository?.path}</Text><When at={l.external_at || l.created_at} /></Table.Td>
              <Table.Td w={30}>{l.url && <ActionIcon component="a" href={l.url} target="_blank" rel="noreferrer" variant="subtle" size="sm"><IconExternalLink size={14} /></ActionIcon>}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      {!d.links.length && <Text size="sm" c="dimmed">No GitLab links yet.</Text>}
      {d.can_edit && !!d.repositories.length && (
        <Group align="flex-end" gap="xs" wrap="wrap">
          <Select size="xs" w={210} label="Repository" value={f.repository_id} onChange={(v) => setF({ ...f, repository_id: v })} data={d.repositories.map((r: any) => ({ value: r.id, label: r.path }))} />
          <Select size="xs" w={140} label="Kind" value={f.kind} onChange={(v) => setF({ ...f, kind: v })} allowDeselect={false} data={[{ value: 'COMMIT', label: 'Commit' }, { value: 'BRANCH', label: 'Branch' }, { value: 'MERGE_REQUEST', label: 'Merge request' }]} />
          <TextInput size="xs" w={170} label={f.kind === 'COMMIT' ? 'SHA' : f.kind === 'BRANCH' ? 'Branch name' : 'MR number'} value={f.ref} onChange={(e) => setF({ ...f, ref: e.currentTarget.value.trim() })} />
          <TextInput size="xs" style={{ flex: 1, minWidth: 160 }} label="Note" value={f.title} onChange={(e) => setF({ ...f, title: e.currentTarget.value })} />
          <Button size="xs" disabled={!f.repository_id || !f.ref} loading={add.isPending} onClick={() => add.mutate(undefined)}>Link by hand</Button>
        </Group>
      )}
    </Stack>
  )
}
