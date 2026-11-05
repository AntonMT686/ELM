import { Badge, Button, Card, Chip, Group, Pagination, SegmentedControl, Select, Table, Text, TextInput } from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { IconFiles, IconPlus, IconSearch } from '@tabler/icons-react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { useDocTypes, useMe } from '../api/hooks'
import type { DocBrief, Paged } from '../api/types'
import { ClassTag, EmptyBlock, FileIcon, PageTitle, StatusTag, TypeBadge, UserAvatar, When } from '../components/common'
import NewDocumentModal from '../components/NewDocumentModal'

const QUICK = [
  { label: 'All', value: 'all' },
  { label: 'My documents', value: 'mine' },
  { label: 'Drafts & rework', value: 'DRAFT,CHANGES_REQUESTED,REJECTED' },
  { label: 'In review', value: 'IN_REVIEW' },
  { label: 'Approved', value: 'APPROVED' },
  { label: 'Released', value: 'RELEASED' },
]

export default function DocumentsPage() {
  const [sp, setSp] = useSearchParams()
  const nav = useNavigate()
  const { data: me } = useMe()
  const types = useDocTypes()
  const [q, setQ] = useState(sp.get('q') || '')
  const [deb] = useDebouncedValue(q, 250)
  const [quick, setQuick] = useState(sp.get('mine') ? 'mine' : sp.get('status') || 'all')
  const [category, setCategory] = useState('all')
  const [project, setProject] = useState<string | null>(null)
  const [type, setType] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [newOpen, setNewOpen] = useState(sp.get('new') === '1')
  useEffect(() => setPage(1), [deb, quick, category, project, type])

  const params = { q: deb, mine: quick === 'mine' || undefined, status: quick !== 'all' && quick !== 'mine' ? quick : undefined, category: category === 'all' ? undefined : category, project_id: project, type_id: type, page, page_size: 25 }
  const { data, isFetching } = useQuery<Paged<DocBrief>>({ queryKey: ['documents', params], queryFn: () => api.get('/documents', params as any), placeholderData: keepPreviousData })

  return (
    <div className="page">
      <PageTitle icon={<IconFiles size={22} />} title="Document register" sub="Every controlled document you can access — engineering, programme and administrative."
        extra={<Button leftSection={<IconPlus size={16} />} onClick={() => setNewOpen(true)}>New document</Button>} />
      <Card mb="md" p="md">
        <Group gap="sm" wrap="wrap">
          <TextInput leftSection={<IconSearch size={16} />} placeholder="Search number, title, keyword…" value={q} onChange={(e) => setQ(e.currentTarget.value)} w={320} />
          <SegmentedControl value={category} onChange={setCategory} data={[{ label: 'All', value: 'all' }, { label: 'Engineering', value: 'ENGINEERING' }, { label: 'Programme', value: 'MANAGEMENT' }, { label: 'Non-engineering', value: 'NON_ENGINEERING' }]} />
          <Select placeholder="Project" clearable w={170} value={project} onChange={setProject} data={(me?.projects || []).map((p) => ({ value: p.id, label: p.code }))} />
          <Select placeholder="Document type" clearable searchable w={260} value={type} onChange={setType} data={(types.data || []).map((t) => ({ value: t.id, label: `${t.code} — ${t.name}` }))} />
        </Group>
        <Chip.Group value={quick} onChange={(v) => setQuick(v as string)}>
          <Group gap={6} mt="sm">{QUICK.map((c) => <Chip key={c.value} value={c.value} size="xs" variant="light">{c.label}</Chip>)}</Group>
        </Chip.Group>
      </Card>
      <Card p={0} style={{ opacity: isFetching ? 0.75 : 1, transition: 'opacity .15s' }}>
        {data && !data.items.length ? <EmptyBlock text="No documents match these filters." action={<Button size="xs" onClick={() => setNewOpen(true)}>Create document</Button>} /> : (
          <Table.ScrollContainer minWidth={1000}>
            <Table>
              <Table.Thead><Table.Tr><Table.Th>Document</Table.Th><Table.Th>Belongs to</Table.Th><Table.Th>Rev</Table.Th><Table.Th>Status</Table.Th><Table.Th>Owner</Table.Th><Table.Th>Updated</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>
                {(data?.items || []).map((d) => (
                  <Table.Tr key={d.id} className="clickable" onClick={() => nav(`/documents/${d.id}`)}>
                    <Table.Td>
                      <Group gap={10} wrap="nowrap">
                        <FileIcon ext={d.current_revision?.ext} size={22} />
                        <div style={{ minWidth: 0 }}>
                          <Group gap={6} wrap="nowrap"><TypeBadge type={d.type} /><Text fw={600} size="sm">{d.number}</Text><ClassTag value={d.classification} /></Group>
                          <Text size="sm" c="dimmed" lineClamp={1}>{d.title}</Text>
                        </div>
                      </Group>
                    </Table.Td>
                    <Table.Td><Text size="sm">{d.project?.code || '—'}{d.item ? ` · ${d.item.code}` : ''}</Text><Text size="xs" c="dimmed">{d.owner_org?.code}</Text></Table.Td>
                    <Table.Td><Badge color="gray">{d.current_revision?.label}{d.current_revision?.iteration ? `.${d.current_revision.iteration}` : ''}</Badge>{d.released_revision && d.released_revision.id !== d.current_revision?.id && <Text size="xs" c="dimmed">rel. {d.released_revision.label}</Text>}</Table.Td>
                    <Table.Td><StatusTag status={d.status} /></Table.Td>
                    <Table.Td><UserAvatar user={d.owner} showName /></Table.Td>
                    <Table.Td><Text size="xs" c="dimmed"><When at={d.updated_at} /></Text></Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
        {!!data?.total && data.total > 25 && <Group justify="space-between" p="md"><Text size="sm" c="dimmed">{data.total} documents</Text><Pagination value={page} onChange={setPage} total={Math.ceil(data.total / 25)} /></Group>}
      </Card>
      <NewDocumentModal opened={newOpen} onClose={() => { setNewOpen(false); if (sp.get('new')) setSp({}) }} />
    </div>
  )
}
