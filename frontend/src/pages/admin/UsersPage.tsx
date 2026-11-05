import { ActionIcon, Badge, Button, Card, Drawer, Group, MultiSelect, PasswordInput, Select, Stack, Switch, Table, Text, TextInput } from '@mantine/core'
import { DateInput } from '@mantine/dates'
import { useDebouncedValue } from '@mantine/hooks'
import { IconPlus, IconSearch, IconTrash, IconUsers } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import { useAction, useMe, useOrgUnits, useRoles } from '../../api/hooks'
import { PageTitle, UserAvatar, When } from '../../components/common'

export default function UsersPage() {
  const [q, setQ] = useState('')
  const [deb] = useDebouncedValue(q, 250)
  const { data = [] } = useQuery<any[]>({ queryKey: ['users', 'admin', deb], queryFn: () => api.get('/users', { q: deb, limit: 500 }) })
  const [sel, setSel] = useState<any | null>(null)
  const current = sel?.id ? data.find((u) => u.id === sel.id) || sel : sel
  return (
    <div className="page">
      <PageTitle icon={<IconUsers size={22} />} title="Users & access" sub="Employees, organization memberships and scoped role assignments (global / directorate / project / item)."
        extra={<Button leftSection={<IconPlus size={16} />} onClick={() => setSel({})}>Add user</Button>} />
      <Card mb="md" p="md"><TextInput leftSection={<IconSearch size={16} />} placeholder="Search by name, username or employee no." value={q} onChange={(e) => setQ(e.currentTarget.value)} w={380} /></Card>
      <Card p={0}>
        <Table>
          <Table.Thead><Table.Tr><Table.Th>User</Table.Th><Table.Th>Employee no.</Table.Th><Table.Th>Organization</Table.Th><Table.Th>Roles (scope)</Table.Th><Table.Th>Last sign-in</Table.Th><Table.Th>Status</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>
            {data.map((u) => (
              <Table.Tr key={u.id} className="clickable" onClick={() => setSel(u)}>
                <Table.Td><UserAvatar user={u} showName sub={`${u.username}${u.is_system_admin ? ' · sysadmin' : ''}`} /></Table.Td>
                <Table.Td>{u.employee_no}</Table.Td>
                <Table.Td><Group gap={4}>{u.orgs?.map((o: any) => <Badge key={o.id} size="sm" color="gray">{o.code}</Badge>)}</Group></Table.Td>
                <Table.Td><Group gap={4}>{u.roles?.slice(0, 4).map((r: any) => <Badge key={r.id} size="sm" variant="outline">{r.role.code} · {r.scope_type === 'GLOBAL' ? 'all' : r.scope_label.split(' ')[0]}</Badge>)}{u.roles?.length > 4 && <Badge size="sm">+{u.roles.length - 4}</Badge>}</Group></Table.Td>
                <Table.Td><Text size="xs" c="dimmed"><When at={u.last_login_at} /></Text></Table.Td>
                <Table.Td><Badge color={u.is_active ? 'teal' : 'gray'}>{u.is_active ? 'Active' : 'Inactive'}</Badge></Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>
      <UserDrawer user={current} onClose={() => setSel(null)} />
    </div>
  )
}

function UserDrawer({ user, onClose }: { user: any | null; onClose: () => void }) {
  const orgs = useOrgUnits()
  const roles = useRoles()
  const { data: me } = useMe()
  const [f, setF] = useState<any>({})
  useEffect(() => { if (user) setF({ username: user.username || '', full_name: user.full_name || '', email: user.email || '', employee_no: user.employee_no || '', designation: user.designation || '', primary_org_unit_id: user.primary_org?.id || null, is_active: user.is_active ?? true, org_unit_ids: (user.orgs || []).map((o: any) => o.id), password: '' }) }, [user])
  const isNew = user && !user.id
  const save = useAction(() => (isNew ? api.post('/users', { ...f, password: f.password || undefined }) : api.put(`/users/${user.id}`, { ...f, password: f.password || undefined })), { success: 'User saved', invalidate: [['users']], onDone: () => isNew && onClose() })
  const [ra, setRa] = useState<any>({ scope_type: 'ORG_UNIT' })
  const assign = useAction(() => api.post('/role-assignments', { ...ra, user_id: user.id, valid_to: ra.valid_to?.toISOString() }), { success: 'Role granted', invalidate: [['users']], onDone: () => setRa({ scope_type: 'ORG_UNIT' }) })
  const revoke = useAction((id: string) => api.del(`/role-assignments/${id}`), { success: 'Role revoked', invalidate: [['users']] })
  const tree = useQuery<any>({ queryKey: ['tree', ra.project_for_item], queryFn: () => api.get(`/projects/${ra.project_for_item}/tree`), enabled: ra.scope_type === 'ENG_ITEM' && !!ra.project_for_item })
  const set = (k: string) => (v: any) => setF({ ...f, [k]: v })
  const orgData = (orgs.data || []).map((o) => ({ value: o.id, label: `${o.code} — ${o.name}` }))
  const scopeData = ra.scope_type === 'ORG_UNIT' ? orgData : ra.scope_type === 'PROJECT' ? (me?.projects || []).map((p) => ({ value: p.id, label: p.code })) : (tree.data?.items || []).map((i: any) => ({ value: i.id, label: `${i.code} — ${i.name}` }))
  return (
    <Drawer opened={!!user} onClose={onClose} position="right" size={560} title={<Text fw={650}>{isNew ? 'New user' : user?.full_name}</Text>}>
      <Stack>
        <Group grow><TextInput label="Username" disabled={!isNew} value={f.username} onChange={(e) => set('username')(e.currentTarget.value)} /><TextInput label="Employee no." value={f.employee_no} onChange={(e) => set('employee_no')(e.currentTarget.value)} /></Group>
        <TextInput label="Full name" value={f.full_name} onChange={(e) => set('full_name')(e.currentTarget.value)} />
        <Group grow><TextInput label="Designation" value={f.designation} onChange={(e) => set('designation')(e.currentTarget.value)} /><TextInput label="Email" value={f.email} onChange={(e) => set('email')(e.currentTarget.value)} /></Group>
        <Select label="Primary department" searchable value={f.primary_org_unit_id} onChange={set('primary_org_unit_id')} data={orgData} />
        <MultiSelect label="Other memberships" searchable value={f.org_unit_ids || []} onChange={set('org_unit_ids')} data={orgData} />
        <PasswordInput label={isNew ? 'Initial password (local fallback account)' : 'Reset password'} description="Min 10 characters. Directory (LDAP/AD) users sign in with directory credentials." value={f.password} onChange={(e) => set('password')(e.currentTarget.value)} />
        <Switch label="Active" checked={f.is_active} onChange={(e) => set('is_active')(e.currentTarget.checked)} />
        <Button loading={save.isPending} onClick={() => save.mutate(undefined)}>Save user</Button>
        {!isNew && user && (
          <Card withBorder p="sm">
            <Text fw={600} mb="xs">Scoped roles</Text>
            {user.roles?.map((r: any) => (
              <Group key={r.id} justify="space-between" py={4}>
                <div><Text size="sm" fw={600}>{r.role.name}</Text><Text size="xs" c="dimmed">{r.scope_type.replace('_', ' ').toLowerCase()} · {r.scope_label}{r.valid_to ? ` · until ${new Date(r.valid_to).toLocaleDateString()}` : ''}</Text></div>
                <ActionIcon color="red" variant="subtle" onClick={() => revoke.mutate(r.id)}><IconTrash size={14} /></ActionIcon>
              </Group>
            ))}
            <Stack gap={6} mt="sm">
              <Select placeholder="Role" value={ra.role_id || null} onChange={(v) => setRa({ ...ra, role_id: v })} data={(roles.data || []).map((r: any) => ({ value: r.id, label: r.name }))} />
              <Group grow>
                <Select value={ra.scope_type} onChange={(v) => setRa({ ...ra, scope_type: v, scope_id: null })} data={[{ value: 'GLOBAL', label: 'Global' }, { value: 'ORG_UNIT', label: 'Directorate / dept' }, { value: 'PROJECT', label: 'Project' }, { value: 'ENG_ITEM', label: 'Engineering item' }]} />
                {ra.scope_type === 'ENG_ITEM' && <Select placeholder="Project" value={ra.project_for_item || null} onChange={(v) => setRa({ ...ra, project_for_item: v })} data={(me?.projects || []).map((p) => ({ value: p.id, label: p.code }))} />}
              </Group>
              {ra.scope_type !== 'GLOBAL' && <Select searchable placeholder="Scope" value={ra.scope_id || null} onChange={(v) => setRa({ ...ra, scope_id: v })} data={scopeData} />}
              <DateInput placeholder="Valid until (optional)" clearable value={ra.valid_to || null} onChange={(v) => setRa({ ...ra, valid_to: v })} />
              <Button variant="light" disabled={!ra.role_id || (ra.scope_type !== 'GLOBAL' && !ra.scope_id)} loading={assign.isPending} onClick={() => assign.mutate(undefined)}>Grant role</Button>
            </Stack>
          </Card>
        )}
      </Stack>
    </Drawer>
  )
}
