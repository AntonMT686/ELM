import { Badge, Button, Card, Checkbox, Group, ScrollArea, Table, Text, TextInput, Tooltip } from '@mantine/core'
import { IconPlus, IconShieldLock } from '@tabler/icons-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, errorText } from '../../api/client'
import { useRoles } from '../../api/hooks'
import { notifications } from '@mantine/notifications'
import { PageTitle } from '../../components/common'

/** Role × permission matrix. Role labels (PGD, TD …) are configuration, never hard-coded. */
export default function RolesPage() {
  const roles = useRoles()
  const qc = useQueryClient()
  const { data: perms = [] } = useQuery<any[]>({ queryKey: ['permissions'], queryFn: () => api.get('/permissions') })
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const toggle = async (r: any, p: string, on: boolean) => {
    const next = on ? [...r.permissions, p] : r.permissions.filter((x: string) => x !== p)
    try { await api.post('/roles', { code: r.code, name: r.name, description: r.description, permissions: next, active: r.active }); qc.invalidateQueries({ queryKey: ['roles'] }) } catch (e) { notifications.show({ color: 'red', message: errorText(e) }) }
  }
  const create = async () => {
    try { await api.post('/roles', { code, name, permissions: [] }); setCode(''); setName(''); qc.invalidateQueries({ queryKey: ['roles'] }) } catch (e) { notifications.show({ color: 'red', message: errorText(e) }) }
  }
  return (
    <div className="page" style={{ maxWidth: 1800 }}>
      <PageTitle icon={<IconShieldLock size={22} />} title="Roles & permissions" sub="Tick to grant. Scope is applied when the role is assigned to a person. System administrators do not automatically get approval or release authority." />
      <Card mb="md" p="md"><Group><TextInput placeholder="ROLE_CODE" value={code} onChange={(e) => setCode(e.currentTarget.value.toUpperCase().replace(/[^A-Z0-9_]/g, ''))} /><TextInput placeholder="Display name" value={name} onChange={(e) => setName(e.currentTarget.value)} w={260} /><Button leftSection={<IconPlus size={16} />} disabled={code.length < 2 || !name} onClick={create}>Add role</Button></Group></Card>
      <Card p={0}>
        <ScrollArea>
          <Table withColumnBorders stickyHeader>
            <Table.Thead><Table.Tr><Table.Th miw={220}>Role</Table.Th>{perms.map((p) => <Table.Th key={p.code} style={{ writingMode: 'vertical-rl', transform: 'rotate(180deg)', height: 150, fontSize: 12 }}><Tooltip label={p.description}><span>{p.code}</span></Tooltip></Table.Th>)}</Table.Tr></Table.Thead>
            <Table.Tbody>
              {(roles.data || []).map((r: any) => (
                <Table.Tr key={r.id}>
                  <Table.Td><Text size="sm" fw={600}>{r.name}</Text><Group gap={4}><Badge size="xs" variant="outline">{r.code}</Badge><Text size="xs" c="dimmed">{r.assignments} assigned</Text></Group></Table.Td>
                  {perms.map((p) => <Table.Td key={p.code} ta="center"><Checkbox size="xs" checked={r.permissions.includes(p.code)} onChange={(e) => toggle(r, p.code, e.currentTarget.checked)} /></Table.Td>)}
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </ScrollArea>
      </Card>
    </div>
  )
}
