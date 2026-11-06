import { Alert, Badge, Button, Checkbox, Code, Group, Modal, SegmentedControl, Select, Stack, Switch, Table, Text, TextInput } from '@mantine/core'
import { IconAlertTriangle, IconFileSearch } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { useAction } from '../api/hooks'

const STATE: Record<string, { color: string; label: string }> = {
  new: { color: 'teal', label: 'new' }, changed: { color: 'blue', label: 'changed' }, unchanged: { color: 'gray', label: 'unchanged' }, locked: { color: 'orange', label: 'approved: not overwritten' },
}

/** Breakdown items of a project, labelled with their level, for "which level does this belong to" pickers. */
export function useItemOptions(projectId: string) {
  const tree = useQuery<any>({ queryKey: ['tree', projectId], queryFn: () => api.get(`/projects/${projectId}/tree`), staleTime: 60_000 })
  return (tree.data?.items || []).map((i: any) => ({ value: i.id, label: `${i.level?.name || 'Item'} · ${i.code} — ${i.name}` }))
}

/** Scan a Word document for requirements (by the source's tag format and/or "shall" statements), preview, import. */
export default function TagFromDocument({ source, projectId, onClose }: { source: any | null; projectId: string; onClose: () => void }) {
  const docs = useQuery<any>({ queryKey: ['documents-mini', projectId], queryFn: () => api.get('/documents', { project_id: projectId, page_size: 200 }), enabled: !!source })
  const items = useItemOptions(projectId)
  const [docId, setDocId] = useState<string | null>(null)
  const [detect, setDetect] = useState('both')
  const [scan, setScan] = useState<any>(null)
  const [picked, setPicked] = useState<number[]>([])
  const [itemId, setItemId] = useState<string | null>(null)
  const [writeTags, setWriteTags] = useState(true)
  const [reason, setReason] = useState('')
  const [done, setDone] = useState<any>(null)
  useEffect(() => { setDocId(source?.document?.id || null); setScan(null); setDone(null); setPicked([]) }, [source?.id])
  const run = useAction(() => api.post(`/requirement-sources/${source.id}/document-scan`, { document_id: docId, detect }), {
    onDone: (r: any) => { setScan(r); setPicked(r.items.filter((i: any) => i.state === 'new' || i.state === 'changed').map((i: any) => i.paragraph)) },
  })
  const imp = useAction(() => api.post(`/requirement-sources/${source.id}/document-import`, { document_id: docId, detect, paragraphs: picked, item_id: itemId, write_tags: writeTags, reason: reason || null }), {
    success: (r: any) => `${r.created.length} new and ${r.updated.length} updated requirement(s)`, invalidate: [['requirements', projectId], ['req-sources', projectId], ['rtm', projectId]], onDone: setDone,
  })
  const toggle = (p: number) => setPicked(picked.includes(p) ? picked.filter((x) => x !== p) : [...picked, p])
  const docOptions = (docs.data?.items || []).map((d: any) => ({ value: d.id, label: `${d.number} — ${d.title}` }))
  return (
    <Modal opened={!!source} onClose={onClose} size="90%" title={`Tag requirements from a document into ${source?.name || ''}`}>
      <Stack>
        <Text size="sm" c="dimmed">
          ELM reads the Word document paragraph by paragraph (tables included) and finds requirements that already carry a tag in this source's format
          {source && <> (<Code>{source.tag_format}</Code>)</>}, and, if you choose, "shall" / "must" statements that have no tag yet. New tags can be written back into the document as a new iteration.
        </Text>
        <Group grow align="flex-end">
          <Select label="Document (.docx)" searchable value={docId} onChange={(v) => { setDocId(v); setScan(null) }} data={docOptions} />
          <div><Text size="sm" fw={500} mb={4}>Find</Text><SegmentedControl fullWidth value={detect} onChange={(v) => { setDetect(v); setScan(null) }} data={[{ value: 'both', label: 'Tags + shall' }, { value: 'tags', label: 'Tagged only' }, { value: 'shall', label: 'Untagged shall' }]} /></div>
          <Button leftSection={<IconFileSearch size={16} />} disabled={!docId} loading={run.isPending} onClick={() => run.mutate(undefined)}>Scan document</Button>
        </Group>
        {scan && !done && (
          <>
            <Group gap="xs">
              <Text size="sm">{scan.document.number} rev {scan.document.revision}.{scan.document.iteration}: {scan.items.length} candidate(s).</Text>
              {Object.entries(scan.counts).map(([k, v]) => !!v && <Badge key={k} size="sm" color={STATE[k].color} variant="light">{String(v)} {STATE[k].label}</Badge>)}
              <Text size="xs" c="dimmed">Next new tag looks like <Code>{scan.example}</Code></Text>
            </Group>
            <div style={{ maxHeight: '45vh', overflow: 'auto' }}>
              <Table verticalSpacing={4} fz="sm" stickyHeader>
                <Table.Thead><Table.Tr><Table.Th w={36}><Checkbox checked={picked.length === scan.items.filter((i: any) => i.state !== 'locked').length && picked.length > 0} onChange={(e) => setPicked(e.currentTarget.checked ? scan.items.filter((i: any) => i.state !== 'locked').map((i: any) => i.paragraph) : [])} /></Table.Th><Table.Th>Section</Table.Th><Table.Th>Tag</Table.Th><Table.Th>Text</Table.Th><Table.Th>What happens</Table.Th></Table.Tr></Table.Thead>
                <Table.Tbody>
                  {scan.items.map((i: any) => (
                    <Table.Tr key={i.paragraph}>
                      <Table.Td><Checkbox disabled={i.state === 'locked'} checked={picked.includes(i.paragraph)} onChange={() => toggle(i.paragraph)} /></Table.Td>
                      <Table.Td><Text size="xs" c="dimmed" maw={180} lineClamp={2}>{i.section || '—'}</Text></Table.Td>
                      <Table.Td>{i.tag ? <Code>{i.tag}</Code> : <Text size="xs" c="dimmed">assigned on import</Text>}</Table.Td>
                      <Table.Td><Text size="xs">{i.text}</Text></Table.Td>
                      <Table.Td><Badge size="xs" color={STATE[i.state].color} variant="light">{STATE[i.state].label}</Badge></Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </div>
            <Group grow align="flex-end">
              <Select label="Breakdown item (level) for new requirements" searchable clearable value={itemId} onChange={setItemId} data={items} description={source?.tag_format?.includes('{ITEM}') || source?.tag_format?.includes('{LEVEL}') ? 'This tag format uses the item, so choose it.' : 'Optional: product, system, subsystem, unit …'} />
              <TextInput label="Reason (for changed requirements)" value={reason} onChange={(e) => setReason(e.currentTarget.value)} />
            </Group>
            <Switch label="Write the new tags back into the document (creates a new iteration of the current revision)" checked={writeTags} disabled={!scan.can_write_tags} onChange={(e) => setWriteTags(e.currentTarget.checked)} />
            {!scan.can_write_tags && <Text size="xs" c="dimmed">The document is in review, released or not editable by you, so new tags are listed for you to put in by hand.</Text>}
            <Group justify="flex-end"><Button variant="default" onClick={onClose}>Close</Button><Button disabled={!picked.length} loading={imp.isPending} onClick={() => imp.mutate(undefined)}>Import {picked.length} requirement(s)</Button></Group>
          </>
        )}
        {done && (
          <Stack>
            <Alert color="teal" title="Imported">{done.created.length} new: {done.created.join(', ') || '—'}. {done.updated.length} updated: {done.updated.join(', ') || '—'}. {done.unchanged.length} unchanged.</Alert>
            {!!done.skipped.length && <Alert color="orange" icon={<IconAlertTriangle size={16} />} title="Not changed">{done.skipped.map((s: any) => <div key={s.tag}>{s.reason}</div>)}</Alert>}
            {done.tags_written && (done.tags_written.written
              ? <Text size="sm">{done.tags_written.count} tag(s) written into the document as iteration {done.tags_written.iteration}.</Text>
              : <Alert color="yellow" title="Tags not written">{done.tags_written.reason}: {Object.values(done.tags_written.tags).join(', ')}</Alert>)}
            <Group justify="flex-end"><Button onClick={onClose}>Done</Button></Group>
          </Stack>
        )}
      </Stack>
    </Modal>
  )
}
