import { Alert, Anchor, Badge, Button, Card, Checkbox, Drawer, FileInput, Group, Loader, Modal, NumberInput, Select, SimpleGrid, Stack, Table, Tabs, Text, Textarea, TextInput, Tooltip } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconAlertTriangle, IconArrowBackUp, IconDownload, IconEdit, IconFileTypePdf, IconLink, IconLock, IconPencil, IconPlus, IconSchema, IconSearch, IconSend, IconUpload } from '@tabler/icons-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api, errorText } from '../api/client'
import { useAction, useProjects } from '../api/hooks'
import { HistoryPanel, LinksPanel, ReasonModal, ReviewPanel, SubmitReviewModal } from '../components/ArtifactParts'
import { EmptyBlock, Hash, PageTitle, UserAvatar, When, fmtSize } from '../components/common'

const LOCKED = ['SUBMITTED', 'UNDER_REVIEW']
const RELEASED = ['APPROVED', 'BASELINED']

export function DesignStatus({ status, states }: { status: string; states?: any[] }) {
  const s = states?.find((x) => x.code === status)
  return <Badge size="sm" variant="light" radius="xl" color={s?.color || 'gray'} style={{ textTransform: 'none' }}>{s?.label || status.replace(/_/g, ' ').toLowerCase()}</Badge>
}

export default function DesignPage() {
  const { projectId } = useParams()
  const nav = useNavigate()
  const projects = useProjects()
  useEffect(() => { if (!projectId && projects.data?.length === 1) nav(`/design/${projects.data[0].id}`, { replace: true }) }, [projectId, projects.data, nav])
  return (
    <div className="page" style={{ maxWidth: 1700 }}>
      <PageTitle icon={<IconSchema size={22} />} title="Design" sub="Design records and engineering artefacts: diagrams, drawings, models and analyses, with versions, review, approval and baseline."
        extra={<Select w={260} placeholder="Choose a project" searchable value={projectId || null} onChange={(v) => v && nav(`/design/${v}`)} allowDeselect={false} data={(projects.data || []).map((p) => ({ value: p.id, label: `${p.code} — ${p.name}` }))} />} />
      {projectId ? <Register key={projectId} projectId={projectId} /> : <EmptyBlock text="Choose a project to see its design records." />}
    </div>
  )
}

function Register({ projectId }: { projectId: string }) {
  const [sp, setSp] = useSearchParams()
  const [q, setQ] = useState('')
  const [status, setStatus] = useState<string | null>(null)
  const [typeId, setTypeId] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const list = useQuery<any>({ queryKey: ['designs', projectId, q, status, typeId], queryFn: () => api.get(`/projects/${projectId}/designs`, { q, status, type_id: typeId }) })
  const types = useQuery<any[]>({ queryKey: ['design-types'], queryFn: () => api.get('/design-types'), staleTime: 300_000 })
  const open = sp.get('open')
  const setOpen = (id: string | null) => { if (id) sp.set('open', id); else sp.delete('open'); setSp(sp, { replace: true }) }
  const d = list.data
  if (list.isError) return <Alert color="red" icon={<IconLock size={16} />}>You do not have access to this project.</Alert>
  return (
    <>
      <Group mb="sm" justify="space-between">
        <Group gap="xs">
          <TextInput size="xs" w={240} leftSection={<IconSearch size={14} />} placeholder="Search ID or text" value={q} onChange={(e) => setQ(e.currentTarget.value)} />
          <Select size="xs" w={170} placeholder="Any status" clearable value={status} onChange={setStatus} data={(d?.states || []).map((s: any) => ({ value: s.code, label: s.label }))} />
          <Select size="xs" w={220} placeholder="Any type" clearable value={typeId} onChange={setTypeId} data={(types.data || []).map((t) => ({ value: t.id, label: t.name }))} />
        </Group>
        {d?.can_create && <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => setCreating(true)}>New design record</Button>}
      </Group>
      {d && !d.items.length ? <EmptyBlock text={q || status || typeId ? 'Nothing matches these filters.' : 'No design records yet.'} /> : (
        <Card withBorder p={0} style={{ overflowX: 'auto' }}>
          <Table highlightOnHover verticalSpacing={6} miw={860}>
            <Table.Thead><Table.Tr><Table.Th>Design record</Table.Th><Table.Th>Type</Table.Th><Table.Th>Status</Table.Th><Table.Th>Version</Table.Th><Table.Th>Owner</Table.Th><Table.Th>Updated</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>
              {(d?.items || []).map((r: any) => (
                <Table.Tr key={r.id} style={{ cursor: 'pointer' }} onClick={() => setOpen(r.id)}>
                  <Table.Td><Group gap={8} wrap="nowrap"><Text size="xs" fw={700} c="dimmed">{r.key}</Text><Text size="sm" lineClamp={1}>{r.title}</Text></Group></Table.Td>
                  <Table.Td><Text size="xs">{r.type?.name}</Text></Table.Td>
                  <Table.Td><DesignStatus status={r.status} states={d.states} /></Table.Td>
                  <Table.Td><Text size="xs">{r.current_version || '—'}{r.baselined_version ? <Tooltip label="Baselined version"><Badge ml={6} size="xs" color="teal" variant="outline">B{r.baselined_version}</Badge></Tooltip> : null}</Text></Table.Td>
                  <Table.Td>{r.owner && <UserAvatar user={r.owner} size={22} />}</Table.Td>
                  <Table.Td><When at={r.updated_at} /></Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Card>
      )}
      <CreateModal opened={creating} projectId={projectId} types={(types.data || []).filter((t) => t.active)} onClose={() => setCreating(false)} onSaved={(r) => { setCreating(false); setOpen(r.id) }} />
      <Drawer opened={!!open} onClose={() => setOpen(null)} position="right" size={760} title={<Text fw={650}>Design record</Text>}>
        {open && <Detail key={open} id={open} projectId={projectId} states={d?.states || []} />}
      </Drawer>
    </>
  )
}

function FieldInputs({ fields, values, set }: { fields: any[]; values: any; set: (k: string, v: any) => void }) {
  return (
    <>
      {fields.map((f) => {
        const v = values[f.key] ?? ''
        if (f.type === 'textarea') return <Textarea key={f.key} label={f.label} required={f.required} autosize minRows={2} value={v} onChange={(e) => set(f.key, e.currentTarget.value)} />
        if (f.type === 'select') return <Select key={f.key} label={f.label} required={f.required} clearable data={f.options || []} value={v || null} onChange={(x) => set(f.key, x)} />
        if (f.type === 'number') return <NumberInput key={f.key} label={f.label} required={f.required} value={v} onChange={(x) => set(f.key, x)} />
        if (f.type === 'checkbox') return <Checkbox key={f.key} label={f.label} checked={!!v} onChange={(e) => set(f.key, e.currentTarget.checked)} />
        return <TextInput key={f.key} label={f.label} required={f.required} value={v} onChange={(e) => set(f.key, e.currentTarget.value)} />
      })}
    </>
  )
}

function CreateModal({ opened, projectId, types, onClose, onSaved }: { opened: boolean; projectId: string; types: any[]; onClose: () => void; onSaved: (r: any) => void }) {
  const [f, setF] = useState<any>({ attributes: {} })
  useEffect(() => { if (opened) setF({ title: '', description: '', type_id: types[0]?.id, attributes: {} }) }, [opened])
  const t = types.find((x) => x.id === f.type_id)
  const save = useAction(() => api.post(`/projects/${projectId}/designs`, f), { success: (r: any) => `${r.key} created`, invalidate: [['designs', projectId]], onDone: onSaved })
  return (
    <Modal opened={opened} onClose={onClose} title="New design record" size="lg">
      <Stack>
        <Select label="Type" required allowDeselect={false} value={f.type_id} onChange={(v) => setF({ ...f, type_id: v, attributes: {} })} data={types.map((x) => ({ value: x.id, label: `${x.name} (${x.category.toLowerCase()})` }))} />
        <TextInput label="Title" required value={f.title} onChange={(e) => setF({ ...f, title: e.currentTarget.value })} />
        <Textarea label="Description" autosize minRows={2} value={f.description} onChange={(e) => setF({ ...f, description: e.currentTarget.value })} />
        {t && <FieldInputs fields={t.fields} values={f.attributes} set={(k, v) => setF({ ...f, attributes: { ...f.attributes, [k]: v } })} />}
        <Group justify="flex-end"><Button variant="default" onClick={onClose}>Cancel</Button><Button disabled={(f.title || '').length < 3 || !f.type_id} loading={save.isPending} onClick={() => save.mutate(undefined)}>Create</Button></Group>
      </Stack>
    </Modal>
  )
}

function Detail({ id, projectId, states }: { id: string; projectId: string; states: any[] }) {
  const q = useQuery<any>({ queryKey: ['design', id], queryFn: () => api.get(`/designs/${id}`) })
  const cfg = useQuery<any>({ queryKey: ['design-config'], queryFn: () => api.get('/design/config'), staleTime: 300_000 })
  const keys = [['design', id], ['designs', projectId], ['rtm', projectId]]
  const [submitting, setSubmitting] = useState(false)
  const [ask, setAsk] = useState<null | 'withdraw' | 'baseline' | { restore: number }>(null)
  const [editing, setEditing] = useState(false)
  const [drawing, setDrawing] = useState(false)
  const submit = useAction((v: any) => api.post(`/designs/${id}/submit`, v), { success: 'Submitted for review', invalidate: keys, onDone: () => setSubmitting(false) })
  const withdraw = useAction((reason: string) => api.post(`/designs/${id}/withdraw`, { reason }), { success: 'Withdrawn', invalidate: keys, onDone: () => setAsk(null) })
  const baseline = useAction((reason: string) => api.post(`/designs/${id}/baseline`, { reason }), { success: 'Baselined', invalidate: keys, onDone: () => setAsk(null) })
  const restore = useAction((v: { n: number; reason: string }) => api.post(`/designs/${id}/versions/${v.n}/restore`, { reason: v.reason }), { success: 'Restored as a new version', invalidate: keys, onDone: () => setAsk(null) })
  if (q.isLoading) return <Group justify="center" py="xl"><Loader type="dots" /></Group>
  if (!q.data) return <Alert color="red">You cannot open this design record.</Alert>
  const d = q.data
  const cur = d.versions[0]
  const drawio = cfg.data?.drawio_url
  return (
    <Stack>
      <div>
        <Group gap={8}><Text size="xs" c="dimmed" fw={700}>{d.key}</Text><DesignStatus status={d.status} states={states} /><Badge size="xs" variant="outline">{d.type.name}</Badge>{d.locked && <Badge size="xs" color="gray" leftSection={<IconLock size={10} />}>locked in review</Badge>}</Group>
        <Text fw={650} size="lg" mt={4}>{d.title}</Text>
        {d.description && <Text size="sm" c="dimmed">{d.description}</Text>}
      </div>
      <Group gap="xs">
        {d.can_edit && !d.locked && drawio && d.type.diagram_editor && <Button size="xs" leftSection={<IconEdit size={14} />} onClick={() => setDrawing(true)}>Edit diagram</Button>}
        {d.can_edit && d.status === 'IN_PROGRESS' && <Button size="xs" variant="light" leftSection={<IconSend size={14} />} disabled={!d.current_version} onClick={() => setSubmitting(true)}>Submit for review</Button>}
        {d.can_edit && d.locked && <Button size="xs" variant="default" leftSection={<IconArrowBackUp size={14} />} onClick={() => setAsk('withdraw')}>Withdraw</Button>}
        {d.can_baseline && <Button size="xs" color="teal" variant="light" leftSection={<IconLock size={14} />} onClick={() => setAsk('baseline')}>Baseline</Button>}
        {d.can_edit && !d.locked && <Button size="xs" variant="default" leftSection={<IconPencil size={14} />} onClick={() => setEditing(true)}>Edit details</Button>}
        <Button size="xs" variant="default" component="a" href={`/api/v1/designs/${id}/report.pdf`} leftSection={<IconFileTypePdf size={14} />}>PDF report</Button>
      </Group>
      {RELEASED.includes(d.status) && d.can_edit && <Alert color="yellow" p="xs" icon={<IconAlertTriangle size={16} />}>This record is {d.status.toLowerCase()}. A change needs a reason and starts a new version; {d.baselined_version ? `baseline version ${d.baselined_version} stays as it was.` : 'it will need approval again.'}</Alert>}
      <Tabs defaultValue="content" keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="content">Content</Tabs.Tab>
          <Tabs.Tab value="versions">Versions ({d.versions.length})</Tabs.Tab>
          <Tabs.Tab value="reviews">Review ({d.reviews.length})</Tabs.Tab>
          <Tabs.Tab value="links">Traceability ({d.links.length})</Tabs.Tab>
          <Tabs.Tab value="history">History</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="content" pt="md">
          <Stack>
            {cur?.preview && <Card withBorder p="xs" style={{ background: 'white' }}><img src={`/api/v1/designs/${id}/versions/${cur.version_no}/preview`} alt={`Version ${cur.version_no} preview`} style={{ maxWidth: '100%', display: 'block', margin: '0 auto' }} /></Card>}
            {cur?.kind === 'LINK' && <Alert icon={<IconLink size={16} />}>Version {cur.version_no} points to <Anchor href={cur.external_url} target="_blank">{cur.external_url}</Anchor></Alert>}
            {cur && !cur.preview && cur.kind !== 'LINK' && <Text size="sm" c="dimmed">Version {cur.version_no}: {cur.source?.name} ({fmtSize(cur.source?.size)}). No preview; download it from Versions.</Text>}
            {!cur && <Text size="sm" c="dimmed">No version yet. {drawio && d.type.diagram_editor ? 'Draw it in the editor or upload a file.' : 'Upload a file or add a link.'}</Text>}
            {d.can_edit && !d.locked && <NewVersion d={d} keys={keys} />}
            {!!d.type.fields.length && (
              <SimpleGrid cols={2}>{d.type.fields.map((f: any) => <div key={f.key}><Text size="xs" c="dimmed">{f.label}</Text><Text size="sm">{String(d.attributes[f.key] ?? '—')}</Text></div>)}</SimpleGrid>
            )}
          </Stack>
        </Tabs.Panel>
        <Tabs.Panel value="versions" pt="md">
          <Table verticalSpacing={6} fz="sm">
            <Table.Tbody>
              {d.versions.map((v: any) => (
                <Table.Tr key={v.version_no}>
                  <Table.Td><Group gap={4}><Text fw={600}>v{v.version_no}</Text>{v.baselined && <Badge size="xs" color="teal">baseline</Badge>}{v.restored_from && <Badge size="xs" variant="outline">from v{v.restored_from}</Badge>}</Group></Table.Td>
                  <Table.Td><Text size="xs">{v.kind.toLowerCase()}</Text><Hash value={v.sha256} /></Table.Td>
                  <Table.Td><Text size="xs" lineClamp={2}>{v.note}</Text></Table.Td>
                  <Table.Td><Text size="xs">{v.created_by?.full_name}</Text><When at={v.created_at} /></Table.Td>
                  <Table.Td>
                    <Group gap={4} wrap="nowrap">
                      {v.source && <Button size="compact-xs" variant="subtle" component="a" href={`/api/v1/designs/${id}/versions/${v.version_no}/source`} leftSection={<IconDownload size={12} />}>{v.source.extension}</Button>}
                      {d.can_edit && !d.locked && v.version_no !== d.current_version && <Button size="compact-xs" variant="subtle" onClick={() => setAsk({ restore: v.version_no })}>Restore</Button>}
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
          {!d.versions.length && <Text size="sm" c="dimmed">No versions yet.</Text>}
        </Tabs.Panel>
        <Tabs.Panel value="reviews" pt="md"><ReviewPanel reviews={d.reviews} decideUrl={(rid) => `/designs/${id}/reviews/${rid}/decide`} keys={keys} /></Tabs.Panel>
        <Tabs.Panel value="links" pt="md">
          <LinksPanel links={d.links} projectId={projectId} addUrl={`/designs/${id}/links`} removeUrl={(lid) => `/designs/${id}/links/${lid}`} keys={keys} canEdit={d.can_edit && d.status !== 'BASELINED'}
            types={['REQUIREMENT', 'DOCUMENT', 'TASK', 'TEST_CASE']} linkTypes={['satisfies', 'describes', 'implements', 'related_to', 'verified_by']} withSection />
        </Tabs.Panel>
        <Tabs.Panel value="history" pt="md"><HistoryPanel history={d.history} /></Tabs.Panel>
      </Tabs>
      <SubmitReviewModal opened={submitting} onClose={() => setSubmitting(false)} title={`Submit ${d.key} version ${d.current_version}`} loading={submit.isPending} onSubmit={(v) => submit.mutate(v)} exclude={[d.owner?.id]} />
      <ReasonModal opened={ask === 'withdraw'} title="Withdraw from review" onClose={() => setAsk(null)} loading={withdraw.isPending} onConfirm={(r) => withdraw.mutate(r)} />
      <ReasonModal opened={ask === 'baseline'} title={`Baseline version ${d.current_version}`} label="Reason / baseline event (e.g. CDR)" onClose={() => setAsk(null)} loading={baseline.isPending} onConfirm={(r) => baseline.mutate(r)} />
      <ReasonModal opened={!!ask && typeof ask === 'object'} title={`Restore version ${typeof ask === 'object' && ask ? ask.restore : ''} as a new version`} onClose={() => setAsk(null)} loading={restore.isPending}
        onConfirm={(r) => typeof ask === 'object' && ask && restore.mutate({ n: ask.restore, reason: r })} />
      {editing && <EditModal d={d} keys={keys} onClose={() => setEditing(false)} />}
      {drawing && drawio && <DrawioEditor d={d} url={drawio} keys={keys} onClose={() => setDrawing(false)} />}
    </Stack>
  )
}

function NewVersion({ d, keys }: { d: any; keys: any[][] }) {
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<File | null>(null)
  const [note, setNote] = useState('')
  const [reason, setReason] = useState('')
  const [url, setUrl] = useState('')
  const needReason = RELEASED.includes(d.status)
  const upload = useAction(() => {
    const fd = new FormData()
    fd.append('file', file!)
    if (preview) fd.append('preview', preview)
    fd.append('note', note)
    if (reason) fd.append('reason', reason)
    fd.append('base_version', String(d.current_version))
    return api.post(`/designs/${d.id}/versions`, fd)
  }, { success: 'New version saved', invalidate: keys, onDone: () => { setFile(null); setPreview(null); setNote(''); setReason('') } })
  const link = useAction(() => api.post(`/designs/${d.id}/link-version`, { url, note, reason: reason || undefined, base_version: d.current_version }), { success: 'Link saved as a new version', invalidate: keys, onDone: () => { setUrl(''); setNote('') } })
  return (
    <Card withBorder>
      <Text size="sm" fw={600} mb="xs">New version</Text>
      <Stack gap="xs">
        <Group grow align="flex-end">
          <FileInput size="xs" label="File" placeholder={d.type.allowed_extensions} value={file} onChange={setFile} accept={d.type.allowed_extensions.split(',').map((x: string) => '.' + x.trim()).join(',')} leftSection={<IconUpload size={14} />} />
          <FileInput size="xs" label="Preview (optional SVG / PNG)" value={preview} onChange={setPreview} accept=".svg,.png,.jpg,.jpeg" />
        </Group>
        <TextInput size="xs" label="Or external link (model repository, CAD vault …)" placeholder="https://" value={url} onChange={(e) => setUrl(e.currentTarget.value)} />
        <TextInput size="xs" label="Note" value={note} onChange={(e) => setNote(e.currentTarget.value)} />
        {needReason && <TextInput size="xs" label="Reason for changing an approved / baselined record" required value={reason} onChange={(e) => setReason(e.currentTarget.value)} />}
        <Group gap="xs">
          <Button size="xs" disabled={!file || (needReason && !reason.trim())} loading={upload.isPending} onClick={() => upload.mutate(undefined)}>Upload version</Button>
          <Button size="xs" variant="light" disabled={!/^https?:\/\//.test(url) || (needReason && !reason.trim())} loading={link.isPending} onClick={() => link.mutate(undefined)}>Save link version</Button>
        </Group>
      </Stack>
    </Card>
  )
}

function EditModal({ d, keys, onClose }: { d: any; keys: any[][]; onClose: () => void }) {
  const [f, setF] = useState<any>({ type_id: d.type.id, title: d.title, description: d.description || '', attributes: { ...d.attributes }, item_id: d.item_id, org_unit_id: d.org_unit_id, reason: '' })
  const save = useAction(() => api.put(`/designs/${d.id}`, f, { version: d.version }), { success: 'Saved', invalidate: keys, onDone: onClose })
  return (
    <Modal opened onClose={onClose} title={`Edit ${d.key}`} size="lg">
      <Stack>
        <TextInput label="Title" required value={f.title} onChange={(e) => setF({ ...f, title: e.currentTarget.value })} />
        <Textarea label="Description" autosize minRows={2} value={f.description} onChange={(e) => setF({ ...f, description: e.currentTarget.value })} />
        <FieldInputs fields={d.type.fields} values={f.attributes} set={(k, v) => setF({ ...f, attributes: { ...f.attributes, [k]: v } })} />
        {RELEASED.includes(d.status) && <TextInput label="Reason for the change" required value={f.reason} onChange={(e) => setF({ ...f, reason: e.currentTarget.value })} />}
        <Group justify="flex-end"><Button variant="default" onClick={onClose}>Cancel</Button><Button loading={save.isPending} onClick={() => save.mutate(undefined)}>Save</Button></Group>
      </Stack>
    </Modal>
  )
}

/**
 * Embedded draw.io (served from the intranet, never embed.diagrams.net). Messages are accepted only from the editor's
 * own origin and its iframe window. Saving sends the XML and an SVG preview to the API with the version it started
 * from; if someone else saved meanwhile, the server refuses and nothing is lost on either side.
 */
function DrawioEditor({ d, url, keys, onClose }: { d: any; url: string; keys: any[][]; onClose: () => void }) {
  const frame = useRef<HTMLIFrameElement>(null)
  const qc = useQueryClient()
  const origin = new URL(url).origin
  const [xml, setXml] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState(false)
  const base = useRef<number>(d.current_version)
  const needReason = RELEASED.includes(d.status)
  const pending = useRef<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      if (!d.current_version || d.versions[0].kind !== 'DIAGRAM') return setXml('')
      const r = await fetch(`/api/v1/designs/${d.id}/versions/${d.current_version}/source`, { credentials: 'same-origin' })
      if (!cancelled) setXml(r.ok ? await r.text() : '')
    }
    load()
    return () => { cancelled = true }
  }, [d.id])

  useEffect(() => {
    const post = (msg: any) => frame.current?.contentWindow?.postMessage(JSON.stringify(msg), origin)
    const onMsg = async (e: MessageEvent) => {
      if (e.origin !== origin || e.source !== frame.current?.contentWindow || typeof e.data !== 'string') return
      let m: any
      try { m = JSON.parse(e.data) } catch { return }
      if (m.event === 'init') post({ action: 'load', xml: xml || '', autosave: 0, title: `${d.key} ${d.title}` })
      else if (m.event === 'save') { pending.current = m.xml; post({ action: 'export', format: 'svg', xml: m.xml, spinKey: 'saving' }) }
      else if (m.event === 'export' && pending.current) {
        const svg = m.data?.startsWith('data:image/svg+xml;base64,') ? atob(m.data.split(',')[1]) : m.data?.startsWith('<svg') ? m.data : null
        setSaving(true)
        try {
          const res: any = await api.post(`/designs/${d.id}/diagram`, { xml: pending.current, svg, base_version: base.current, reason: reason || undefined })
          base.current = res.current_version
          post({ action: 'status', message: `Saved as version ${res.current_version}`, modified: false })
          notifications.show({ color: 'teal', message: `${d.key}: version ${res.current_version} saved` })
          keys.forEach((k) => qc.invalidateQueries({ queryKey: k }))
        } catch (err) {
          post({ action: 'status', message: 'Not saved', modified: true })
          notifications.show({ color: 'red', title: 'Diagram not saved', message: errorText(err), autoClose: 10000 })
        } finally { setSaving(false); pending.current = null }
      } else if (m.event === 'exit') onClose()
    }
    window.addEventListener('message', onMsg)
    return () => window.removeEventListener('message', onMsg)
  }, [xml, reason, origin])

  const blocked = needReason && !reason.trim()
  return (
    <Modal opened onClose={onClose} fullScreen title={<Group gap="xs"><Text fw={650}>{d.key} — {d.title}</Text>{saving && <Loader size="xs" />}</Group>} padding="xs">
      {needReason && <TextInput mb="xs" size="xs" label="Reason for changing this approved / baselined record (needed before you save)" required value={reason} onChange={(e) => setReason(e.currentTarget.value)} />}
      {xml === null ? <Loader /> : blocked ? <Alert color="yellow">Enter the reason first; the editor opens once it is filled in.</Alert> : (
        <iframe ref={frame} title="draw.io" src={`${url}/?embed=1&proto=json&spin=1&ui=atlas&saveAndExit=1&noExitBtn=0&libraries=1&configure=0&offline=1`} style={{ width: '100%', height: 'calc(100vh - 120px)', border: 0 }} />
      )}
    </Modal>
  )
}
