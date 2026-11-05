import { Alert, Badge, Button, Card, Checkbox, Group, Modal, Pagination, SegmentedControl, Select, Stack, Table, Tabs, Text, Textarea, TextInput } from '@mantine/core'
import { useDebouncedValue, useDisclosure } from '@mantine/hooks'
import { modals } from '@mantine/modals'
import { IconCertificate, IconPackage, IconPlus, IconSearch } from '@tabler/icons-react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { can, useAction, useDocTypes, useMe, useOrgUnits } from '../api/hooks'
import { EmptyBlock, FileIcon, Hash, PageTitle, StatusTag, UserAvatar, When } from '../components/common'

export default function ReleasesPage() {
  const { data: me } = useMe()
  const [tab, setTab] = useState<string | null>('register')
  return (
    <div className="page">
      <PageTitle icon={<IconCertificate size={22} />} title="Central Release Register" sub="Formally released revisions — immutable, hash-verified, with approval and signature evidence." />
      <Tabs value={tab} onChange={setTab} mb="md">
        <Tabs.List><Tabs.Tab value="register">Released documents</Tabs.Tab><Tabs.Tab value="packages" leftSection={<IconPackage size={14} />}>Release packages</Tabs.Tab></Tabs.List>
      </Tabs>
      {tab === 'register' ? <Register canWithdraw={can(me, 'doc.withdraw')} /> : <Packages canRelease={can(me, 'doc.release')} />}
    </div>
  )
}

function Register({ canWithdraw }: { canWithdraw: boolean }) {
  const nav = useNavigate()
  const { data: me } = useMe()
  const orgs = useOrgUnits()
  const types = useDocTypes()
  const [q, setQ] = useState('')
  const [deb] = useDebouncedValue(q, 250)
  const [status, setStatus] = useState('RELEASED')
  const [project, setProject] = useState<string | null>(null)
  const [org, setOrg] = useState<string | null>(null)
  const [type, setType] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const params = { q: deb, status: status === 'all' ? 'RELEASED,SUPERSEDED,WITHDRAWN' : status, project_id: project, org_unit_id: org, type_id: type, page, page_size: 25 }
  const { data } = useQuery<any>({ queryKey: ['register', params], queryFn: () => api.get('/release-register', params as any), placeholderData: keepPreviousData })
  const withdraw = useAction((v: { id: string; reason: string }) => api.post(`/release-register/${v.id}/withdraw`, { reason: v.reason }), { success: 'Release withdrawn', invalidate: [['register']] })
  const askWithdraw = (e: any) => {
    let reason = ''
    modals.openConfirmModal({
      title: `Withdraw ${e.release_no}?`, labels: { confirm: 'Withdraw', cancel: 'Cancel' }, confirmProps: { color: 'red' },
      children: <Textarea label="Mandatory reason" autosize minRows={2} onChange={(ev) => (reason = ev.currentTarget.value)} />,
      onConfirm: () => withdraw.mutate({ id: e.id, reason }),
    })
  }
  return (
    <>
      <Card mb="md" p="md">
        <Group gap="sm">
          <TextInput leftSection={<IconSearch size={16} />} placeholder="Release no., document number or title" w={320} value={q} onChange={(e) => setQ(e.currentTarget.value)} />
          <SegmentedControl value={status} onChange={setStatus} data={[{ label: 'Current', value: 'RELEASED' }, { label: 'Superseded', value: 'SUPERSEDED' }, { label: 'Withdrawn', value: 'WITHDRAWN' }, { label: 'All', value: 'all' }]} />
          <Select placeholder="Project" clearable w={150} value={project} onChange={setProject} data={(me?.projects || []).map((p) => ({ value: p.id, label: p.code }))} />
          <Select placeholder="Directorate" clearable searchable w={220} value={org} onChange={setOrg} data={(orgs.data || []).filter((o) => o.unit_type !== 'ORGANIZATION').map((o) => ({ value: o.id, label: `${o.code} — ${o.name}` }))} />
          <Select placeholder="Type" clearable w={200} value={type} onChange={setType} data={(types.data || []).map((t) => ({ value: t.id, label: t.name }))} />
        </Group>
      </Card>
      <Card p={0}>
        {!data?.items?.length ? <EmptyBlock text="No released documents match." /> : (
          <Table.ScrollContainer minWidth={1100}>
            <Table>
              <Table.Thead><Table.Tr><Table.Th>Release</Table.Th><Table.Th>Document</Table.Th><Table.Th>Rev</Table.Th><Table.Th>Scope</Table.Th><Table.Th>Evidence</Table.Th><Table.Th>Released</Table.Th><Table.Th /></Table.Tr></Table.Thead>
              <Table.Tbody>
                {data.items.map((e: any) => (
                  <Table.Tr key={e.id} className="clickable" onClick={() => nav(`/documents/${e.document.id}`)}>
                    <Table.Td><Text fw={650} size="sm">{e.release_no}</Text><StatusTag status={e.status} />{e.package && <Badge size="xs" color="grape" ml={4}>{e.package.code}</Badge>}</Table.Td>
                    <Table.Td><Group gap={8} wrap="nowrap"><FileIcon ext={e.revision.ext} /><div><Group gap={6}><span className="lvl" style={{ background: e.type.color || '#64748b' }}>{e.type.code}</span><Text size="sm" fw={600}>{e.document.number}</Text></Group><Text size="xs" c="dimmed" lineClamp={1}>{e.document.title}</Text></div></Group></Table.Td>
                    <Table.Td><Badge color="dark">{e.revision.label}</Badge></Table.Td>
                    <Table.Td><Text size="sm">{e.project?.code}{e.item ? ` · ${e.item.code}` : ''}</Text><Text size="xs" c="dimmed">{e.owner_org?.code}</Text></Table.Td>
                    <Table.Td><Badge color="yellow" size="sm">{e.signature_count} signature(s)</Badge><div><Hash value={e.sha256} /></div></Table.Td>
                    <Table.Td><UserAvatar user={e.released_by} size={22} /> <Text size="xs" c="dimmed" span><When at={e.released_at} /></Text></Table.Td>
                    <Table.Td onClick={(ev) => ev.stopPropagation()}>{canWithdraw && e.status === 'RELEASED' && <Button size="compact-xs" variant="subtle" color="red" onClick={() => askWithdraw(e)}>Withdraw</Button>}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
        {data?.total > 25 && <Group justify="flex-end" p="md"><Pagination value={page} onChange={setPage} total={Math.ceil(data.total / 25)} /></Group>}
      </Card>
    </>
  )
}

function Packages({ canRelease }: { canRelease: boolean }) {
  const { data, refetch } = useQuery<any[]>({ queryKey: ['packages'], queryFn: () => api.get('/release-packages') })
  const [open, m] = useDisclosure(false)
  const rel = useAction((id: string) => api.post(`/release-packages/${id}/release`), { success: 'Package released — manifest sealed', invalidate: [['packages'], ['register']] })
  return (
    <Stack>
      {canRelease && <Group justify="flex-end"><Button leftSection={<IconPlus size={16} />} onClick={m.open}>Prepare package</Button></Group>}
      {!data?.length && <Card><EmptyBlock text="No release packages yet. Group approved documents (e.g. an LRU data pack) and release them together with one manifest." /></Card>}
      {data?.map((p) => (
        <Card key={p.id}>
          <Group justify="space-between">
            <div><Group gap={8}><IconPackage size={18} /><Text fw={650}>{p.code}</Text><StatusTag status={p.status} /></Group><Text size="sm">{p.title}</Text></div>
            <Group>{p.manifest_sha256 && <Text size="xs" c="dimmed" component="div">Manifest <Hash value={p.manifest_sha256} /></Text>}{p.status === 'DRAFT' && canRelease && <Button color="teal" size="xs" loading={rel.isPending} onClick={() => rel.mutate(p.id)}>Release package</Button>}</Group>
          </Group>
          <Table mt="sm"><Table.Tbody>{p.items.map((i: any) => <Table.Tr key={i.revision.id}><Table.Td><b>{i.document.number}</b></Table.Td><Table.Td>{i.document.title}</Table.Td><Table.Td>rev {i.revision.label}</Table.Td><Table.Td><StatusTag status={i.revision.status} /></Table.Td></Table.Tr>)}</Table.Tbody></Table>
        </Card>
      ))}
      <NewPackage opened={open} onClose={() => { m.close(); refetch() }} />
    </Stack>
  )
}

function NewPackage({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const { data: me } = useMe()
  const [title, setTitle] = useState('')
  const [project, setProject] = useState<string | null>(null)
  const [note, setNote] = useState('')
  const [sel, setSel] = useState<string[]>([])
  const approved = useQuery<any>({ queryKey: ['documents', 'approved', project], queryFn: () => api.get('/documents', { status: 'APPROVED', project_id: project || undefined, page_size: 200 }), enabled: opened })
  const act = useAction(() => api.post('/release-packages', { title, project_id: project, release_note: note, document_ids: sel }), { success: 'Package prepared', onDone: () => { setSel([]); setTitle(''); onClose() } })
  return (
    <Modal opened={opened} onClose={onClose} size={700} title="Prepare release package">
      <Stack>
        <TextInput label="Package title" required value={title} onChange={(e) => setTitle(e.currentTarget.value)} placeholder="e.g. FCC LRU data pack — CDR baseline" />
        <Select label="Project" clearable value={project} onChange={setProject} data={(me?.projects || []).map((p) => ({ value: p.id, label: p.code }))} />
        <Textarea label="Release note" value={note} onChange={(e) => setNote(e.currentTarget.value)} autosize minRows={2} />
        <Text fw={600} size="sm">Approved documents ready for release</Text>
        {!approved.data?.items?.length ? <Alert variant="light" color="gray">No approved documents in this scope.</Alert> : (
          <Checkbox.Group value={sel} onChange={setSel}>
            <Stack gap={6}>{approved.data.items.map((d: any) => <Checkbox key={d.id} value={d.id} label={<Text size="sm"><b>{d.number}</b> rev {d.current_revision?.label} — {d.title}</Text>} />)}</Stack>
          </Checkbox.Group>
        )}
        <Group justify="flex-end"><Button variant="default" onClick={onClose}>Cancel</Button><Button disabled={!title || !sel.length} loading={act.isPending} onClick={() => act.mutate(undefined)}>Create package</Button></Group>
      </Stack>
    </Modal>
  )
}
