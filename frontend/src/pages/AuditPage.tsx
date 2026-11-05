import { Alert, Badge, Button, Card, Code, Group, Pagination, Select, Table, Text, TextInput, Tooltip } from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { IconFingerprint, IconSearch, IconShieldCheck, IconShieldX } from '@tabler/icons-react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import { PageTitle, UserAvatar } from '../components/common'

export default function AuditPage() {
  const [q, setQ] = useState('')
  const [deb] = useDebouncedValue(q, 300)
  const [action, setAction] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const params = { q: deb, action, page, page_size: 50 }
  const { data } = useQuery<any>({ queryKey: ['audit', params], queryFn: () => api.get('/audit', params as any), placeholderData: keepPreviousData })
  const [verify, setVerify] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const run = async () => { setBusy(true); try { setVerify(await api.get('/audit/verify')) } finally { setBusy(false) } }
  return (
    <div className="page">
      <PageTitle icon={<IconFingerprint size={22} />} title="Audit trail" sub="Append-only, hash-chained record of every sensitive action. Viewing the trail is itself audited."
        extra={<Button leftSection={<IconShieldCheck size={16} />} loading={busy} onClick={run}>Verify chain integrity</Button>} />
      {verify && (verify.valid
        ? <Alert color="teal" icon={<IconShieldCheck />} mb="md" title="Audit chain intact">{verify.checked} events verified — no tampering detected.</Alert>
        : <Alert color="red" icon={<IconShieldX />} mb="md" title="Audit chain broken">Integrity failure at event #{verify.broken_at_seq}. Escalate to security.</Alert>)}
      <Card mb="md" p="md">
        <Group>
          <TextInput leftSection={<IconSearch size={16} />} placeholder="Search summaries…" w={340} value={q} onChange={(e) => setQ(e.currentTarget.value)} />
          <Select placeholder="Action family" clearable w={220} value={action} onChange={setAction} data={['auth', 'document', 'workflow', 'signature', 'release', 'role', 'user', 'org', 'project', 'item', 'task', 'audit'].map((v) => ({ value: v, label: v }))} />
          <Text size="sm" c="dimmed">{data?.total ?? 0} events</Text>
        </Group>
      </Card>
      <Card p={0}>
        <Table.ScrollContainer minWidth={1000}>
          <Table fz="sm">
            <Table.Thead><Table.Tr><Table.Th>#</Table.Th><Table.Th>When</Table.Th><Table.Th>Actor</Table.Th><Table.Th>Action</Table.Th><Table.Th>Summary</Table.Th><Table.Th>Outcome</Table.Th><Table.Th>Hash</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>
              {(data?.items || []).map((e: any) => (
                <Table.Tr key={e.seq}>
                  <Table.Td><Text size="xs" c="dimmed">{e.seq}</Text></Table.Td>
                  <Table.Td><Text size="xs">{new Date(e.at).toLocaleString()}</Text></Table.Td>
                  <Table.Td>{e.actor ? <UserAvatar user={e.actor} showName sub={e.on_behalf_of ? `for ${e.on_behalf_of.full_name}` : e.ip} /> : <Text size="xs" c="dimmed">system</Text>}</Table.Td>
                  <Table.Td><Code>{e.action}</Code></Table.Td>
                  <Table.Td><Tooltip multiline w={420} label={e.data || 'no details'} disabled={!e.data}><Text size="sm">{e.summary}</Text></Tooltip></Table.Td>
                  <Table.Td><Badge size="sm" color={e.outcome === 'SUCCESS' ? 'teal' : 'red'}>{e.outcome}</Badge></Table.Td>
                  <Table.Td><span className="hash">{e.hash.slice(0, 12)}</span></Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
        {data?.total > 50 && <Group justify="flex-end" p="md"><Pagination value={page} onChange={setPage} total={Math.ceil(data.total / 50)} /></Group>}
      </Card>
    </div>
  )
}
