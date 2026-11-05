import { Group, Loader, Text } from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { Spotlight, spotlight } from '@mantine/spotlight'
import { IconBinaryTree2, IconBolt, IconFileText, IconSearch, IconUser } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { StatusTag } from './common'

export const openPalette = () => spotlight.open()

const QUICK = [
  { title: 'Open my action inbox', path: '/inbox' },
  { title: 'Create a new document', path: '/documents?new=1' },
  { title: 'Browse the product structure (Aircraft → System → LRU)', path: '/explorer' },
  { title: 'Search the Release Register', path: '/releases' },
  { title: 'My tasks board', path: '/tasks' },
]

/** Ctrl/⌘+K: jump anywhere — documents, configuration items, people, actions. */
export default function CommandPalette() {
  const nav = useNavigate()
  const [q, setQ] = useState('')
  const [deb] = useDebouncedValue(q.trim(), 180)
  const { data, isFetching } = useQuery({ queryKey: ['search', deb], queryFn: () => api.get('/search', { q: deb }), enabled: deb.length >= 2 })
  const go = (p: string) => () => { nav(p); spotlight.close() }

  const actions =
    deb.length < 2
      ? QUICK.map((x) => <Spotlight.Action key={x.path} label={x.title} leftSection={<IconBolt size={18} />} onClick={go(x.path)} />)
      : [
          ...(data?.documents || []).map((d: any) => (
            <Spotlight.Action key={'d' + d.id} onClick={go(`/documents/${d.id}`)}>
              <Group wrap="nowrap" w="100%"><IconFileText size={18} /><div style={{ flex: 1, minWidth: 0 }}><Text fw={600} size="sm">{d.number}</Text><Text size="xs" c="dimmed" truncate>{d.title}</Text></div><StatusTag status={d.status} /></Group>
            </Spotlight.Action>
          )),
          ...(data?.items || []).map((i: any) => (
            <Spotlight.Action key={'i' + i.id} leftSection={<IconBinaryTree2 size={18} />} label={`${i.code} — ${i.name}`} description={`${i.level} · ${i.project}`} onClick={go(`/explorer/${i.project_id}?item=${i.id}`)} />
          )),
          ...(data?.people || []).map((u: any) => <Spotlight.Action key={'u' + u.id} leftSection={<IconUser size={18} />} label={u.full_name} description={u.designation} onClick={go('/documents')} />),
        ]

  return (
    <Spotlight.Root query={q} onQueryChange={setQ} shortcut={['mod + K', '/']} scrollable maxHeight={460} radius="lg">
      <Spotlight.Search placeholder="Search documents, LRUs, systems, people…  (try “FCC” or “ICD”)" leftSection={<IconSearch size={18} />} rightSection={isFetching ? <Loader size="xs" /> : null} />
      <Spotlight.ActionsList>
        {deb.length < 2 && <Spotlight.ActionsGroup label="Quick actions">{actions}</Spotlight.ActionsGroup>}
        {deb.length >= 2 && (actions.length ? actions : <Spotlight.Empty>{isFetching ? 'Searching…' : 'No matches'}</Spotlight.Empty>)}
      </Spotlight.ActionsList>
    </Spotlight.Root>
  )
}
