import { Alert, Badge, Button, Card, Center, Grid, Group, Loader, Menu, Modal, MultiSelect, Select, Stack, Table, Tabs, Text, Textarea, TextInput, ThemeIcon, Timeline, Title, Tooltip } from '@mantine/core'
import { DateInput } from '@mantine/dates'
import { Dropzone } from '@mantine/dropzone'
import { useDisclosure } from '@mantine/hooks'
import { notifications } from '@mantine/notifications'
import {
  IconArrowBackUp, IconCertificate, IconCheck, IconChevronDown, IconCloudUpload, IconDots, IconDownload, IconEdit, IconFilePlus, IconGitFork, IconHistory,
  IconLink, IconMessage, IconRosetteDiscountCheck, IconSend, IconShare, IconShieldCheck, IconX,
} from '@tabler/icons-react'
import { Background, Controls, ReactFlow, type Edge, type Node } from '@xyflow/react'
import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api, errorText, fileUrl } from '../api/client'
import { useAction, useDoc, useDocWorkflow, useOrgUnits } from '../api/hooks'
import type { DocFull } from '../api/types'
import { ClassTag, EmptyBlock, FileIcon, fmtSize, Hash, LevelTag, StatusTag, TypeBadge, UserAvatar, When } from '../components/common'
import DocumentPreview from '../components/DocumentPreview'
import LifecycleTracker from '../components/LifecycleTracker'
import NewDocumentModal from '../components/NewDocumentModal'
import NotFound from '../components/NotFound'
import { UserSelect } from './InboxPage'

export default function DocumentPage() {
  const { id } = useParams()
  const nav = useNavigate()
  const [sp, setSp] = useSearchParams()
  const { data: d, isLoading, error } = useDoc(id)
  const wf = useDocWorkflow(id)
  const [submit, submitM] = useDisclosure(false)
  const [release, releaseM] = useDisclosure(false)
  const [upload, uploadM] = useDisclosure(false)
  const [revise, reviseM] = useDisclosure(false)
  const [share, shareM] = useDisclosure(false)
  const [relate, relateM] = useDisclosure(false)
  const [child, childM] = useDisclosure(false)
  const inv = [['doc', id], ['doc-wf', id], ['documents'], ['inbox'], ['dashboard']]
  const withdraw = useAction((reason: string) => api.post(`/documents/${id}/withdraw-submission`, { reason }), { success: 'Submission withdrawn — document is editable again', invalidate: inv })

  if (isLoading) return <Center h="60vh"><Loader /></Center>
  if (error || !d) return <NotFound title="Document not available" text={errorText(error)} />
  const cur = d.current_revision_full
  const active = wf.data?.find((r) => r.status === 'ACTIVE')
  const latest = active || wf.data?.[0]
  const p = d.permissions
  const tab = sp.get('tab') || 'preview'

  return (
    <div className="page" style={{ maxWidth: 1800 }}>
      <Card mb="md" p="lg">
        <Group justify="space-between" align="flex-start" wrap="wrap" gap="md">
          <Group align="flex-start" wrap="nowrap" gap="md" style={{ minWidth: 0 }}>
            <ThemeIcon size={54} radius="md" variant="light" color="gray"><FileIcon ext={cur?.file?.extension} size={30} /></ThemeIcon>
            <div style={{ minWidth: 0 }}>
              <Group gap={8}><TypeBadge type={d.type} /><Text fw={700} size="lg">{d.number}</Text><Badge color="dark" variant="light">Rev {cur?.label}{cur?.iteration ? `.${cur.iteration}` : ''}</Badge><StatusTag status={d.status} locked={cur?.locked} /><ClassTag value={d.classification} /></Group>
              <Title order={3} mt={4}>{d.title}</Title>
              <Group gap={14} mt={6}>
                {d.project && <Text size="xs" c="dimmed">Project <b>{d.project.code}</b></Text>}
                {d.item && <Group gap={4}><LevelTag level={d.item.level} /><Text size="xs" className="clickable" onClick={() => nav(`/explorer/${d.project?.id}?item=${d.item!.id}`)}><b>{d.item.code}</b> {d.item.name}</Text></Group>}
                {d.owner_org && <Text size="xs" c="dimmed">Owner <b>{d.owner_org.code}</b></Text>}
                <Group gap={4}><UserAvatar user={d.owner} size={18} /><Text size="xs" c="dimmed">{d.owner?.full_name}</Text></Group>
                {cur?.sha256 && <Text size="xs" c="dimmed" component="div">SHA-256 <Hash value={cur.sha256} /></Text>}
              </Group>
            </div>
          </Group>
          <Group gap="xs">
            {d.my_task_id && <Button color="orange" onClick={() => nav(`/inbox?task=${d.my_task_id}`)}>Your action is pending</Button>}
            {p.edit && cur?.file && ['docx', 'xlsx', 'pptx'].includes(cur.file.extension) && <Button leftSection={<IconEdit size={16} />} onClick={() => nav(`/documents/${d.id}/edit`)}>Edit online</Button>}
            {p.submit && <Button color="brand" variant="filled" leftSection={<IconSend size={16} />} onClick={submitM.open}>Submit for review</Button>}
            {p.release && <Button color="teal" leftSection={<IconCertificate size={16} />} onClick={releaseM.open}>Release</Button>}
            {p.revise && <Button variant="light" leftSection={<IconGitFork size={16} />} onClick={reviseM.open}>Start revision {String.fromCharCode((cur?.label.charCodeAt(0) || 64) + 1)}</Button>}
            <Menu position="bottom-end" width={230}>
              <Menu.Target><Button variant="default" rightSection={<IconChevronDown size={14} />} leftSection={<IconDots size={16} />}>More</Button></Menu.Target>
              <Menu.Dropdown>
                {p.edit && <Menu.Item leftSection={<IconCloudUpload size={16} />} onClick={uploadM.open}>Upload new content</Menu.Item>}
                {p.download && cur?.file && <Menu.Item leftSection={<IconDownload size={16} />} component="a" href={fileUrl(d.id, cur.id, false)}>Download</Menu.Item>}
                {p.share && <Menu.Item leftSection={<IconShare size={16} />} onClick={shareM.open}>Share with team / person</Menu.Item>}
                {p.edit && <Menu.Item leftSection={<IconLink size={16} />} onClick={relateM.open}>Link related document</Menu.Item>}
                <Menu.Item leftSection={<IconFilePlus size={16} />} onClick={childM.open}>Create child document</Menu.Item>
                {p.withdraw_submission && <><Menu.Divider /><Menu.Item color="red" leftSection={<IconArrowBackUp size={16} />} onClick={() => { const r = window.prompt('Reason for withdrawing the submission?'); if (r && r.length >= 3) withdraw.mutate(r) }}>Withdraw submission</Menu.Item></>}
              </Menu.Dropdown>
            </Menu>
          </Group>
        </Group>
        {d.status === 'CHANGES_REQUESTED' && latest && <Alert mt="md" color="orange" variant="light" icon={<IconArrowBackUp />} title="Changes were requested">
          {latest.stages.flatMap((s) => s.tasks).filter((t) => t.status === 'CHANGES_REQUESTED' || t.status === 'REJECTED').map((t) => <div key={t.id}><b>{t.assignee.full_name}:</b> {t.comment}</div>)}
          <Text size="xs" mt={4}>Update the content (edit online or upload), then submit again — a new review cycle starts on the new content.</Text>
        </Alert>}
        {latest && <div style={{ marginTop: 16 }}><Group justify="space-between" mb={6}><Text size="sm" fw={600}>{latest.workflow.name} <Text span c="dimmed" size="xs">v{latest.workflow.version_no} · cycle {latest.cycle_no} · rev {latest.revision.label}</Text></Text><StatusTag status={latest.status} /></Group><LifecycleTracker run={latest} /></div>}
      </Card>

      <Card p={0}>
        <Tabs value={tab} onChange={(v) => setSp({ tab: v || 'preview' }, { replace: true })}>
          <Tabs.List px="md" pt={6}>
            <Tabs.Tab value="preview">Preview</Tabs.Tab>
            <Tabs.Tab value="reviews" leftSection={<IconHistory size={14} />}>Review history ({wf.data?.length || 0})</Tabs.Tab>
            <Tabs.Tab value="revisions">Revisions</Tabs.Tab>
            <Tabs.Tab value="signatures" leftSection={<IconRosetteDiscountCheck size={14} />}>Signatures ({d.signatures.length})</Tabs.Tab>
            <Tabs.Tab value="relations">Relations ({d.relations.length})</Tabs.Tab>
            <Tabs.Tab value="discussion" leftSection={<IconMessage size={14} />}>Discussion</Tabs.Tab>
            <Tabs.Tab value="access">Access</Tabs.Tab>
            <Tabs.Tab value="audit">Audit trail</Tabs.Tab>
          </Tabs.List>
          <div style={{ padding: 16 }}>
            {tab === 'preview' && (cur ? <DocumentPreview docId={d.id} revisionId={cur.id} ext={cur.file?.extension} height={760} /> : null)}
            {tab === 'reviews' && <ReviewHistory runs={wf.data || []} />}
            {tab === 'revisions' && <Revisions d={d} />}
            {tab === 'signatures' && <Signatures d={d} />}
            {tab === 'relations' && <Relations d={d} />}
            {tab === 'discussion' && <Discussion docId={d.id} />}
            {tab === 'access' && <Access d={d} onShare={shareM.open} />}
            {tab === 'audit' && <AuditTab docId={d.id} />}
          </div>
        </Tabs>
      </Card>

      <SubmitModal opened={submit} onClose={submitM.close} d={d} />
      <ReleaseModal opened={release} onClose={releaseM.close} d={d} />
      <UploadModal opened={upload} onClose={uploadM.close} d={d} />
      <ReviseModal opened={revise} onClose={reviseM.close} d={d} />
      <ShareModal opened={share} onClose={shareM.close} d={d} />
      <RelateModal opened={relate} onClose={relateM.close} d={d} />
      <NewDocumentModal opened={child} onClose={childM.close} projectId={d.project?.id} itemId={d.item?.id} parentDocId={d.id} />
    </div>
  )
}

// ---------------------------------------------------------------- submit (smart reviewer picking)
function SubmitModal({ opened, onClose, d }: { opened: boolean; onClose: () => void; d: DocFull }) {
  const plan = useQuery({ queryKey: ['plan', d.id], queryFn: () => api.get(`/documents/${d.id}/workflow-plan`), enabled: opened })
  const [picks, setPicks] = useState<Record<string, string[]>>({})
  const [comment, setComment] = useState('')
  const act = useAction(() => api.post(`/documents/${d.id}/submit`, { picks, comment: comment || undefined, version: d.version }), {
    success: 'Submitted — reviewers have been notified', invalidate: [['doc', d.id], ['doc-wf', d.id], ['documents'], ['inbox'], ['dashboard']], onDone: onClose,
  })
  const stages = plan.data?.stages || []
  const need = stages.filter((s: any) => s.assignee.kind === 'pick' && !s.skipped)
  const ready = need.every((s: any) => (picks[s.key] || []).length >= (s.assignee.min || 1))
  return (
    <Modal opened={opened} onClose={onClose} size={720} title={<Text fw={650} size="lg">Submit {d.number} rev {d.current_revision?.label} for review</Text>}>
      {plan.error ? <Alert color="red">{errorText(plan.error)}</Alert> : !plan.data ? <Center py="xl"><Loader /></Center> : (
        <Stack>
          <Alert variant="light" icon={<IconShieldCheck />}>Workflow <b>{plan.data.definition.name}</b> v{plan.data.version_no}. Reviewers will see exactly this content (hash-locked). Editing is locked while in review.</Alert>
          <Timeline active={0} bulletSize={26} lineWidth={2}>
            {stages.map((s: any, i: number) => (
              <Timeline.Item key={s.key} bullet={<Text size="xs" fw={700}>{i + 1}</Text>} title={<Group gap={6}><Text fw={600} size="sm">{s.name}</Text><Badge size="xs" color="gray">{s.type}</Badge>{s.skipped && <Badge size="xs" color="gray" variant="outline">skipped by rule</Badge>}{s.mode === 'quorum' && <Badge size="xs">quorum {s.quorum}</Badge>}{s.mode === 'all' && s.assignee.kind === 'pick' && <Badge size="xs" variant="outline">all must accept</Badge>}</Group>}>
                {s.type === 'prepare' && <Text size="xs" c="dimmed">You — submitting now</Text>}
                {s.type === 'signature' && <Text size="xs" c="dimmed">Signed by: {s.signers_from.map((k: string) => stages.find((x: any) => x.key === k)?.name).join(', ')}</Text>}
                {s.assignee.kind === 'role' && <Text size="xs" c="dimmed">Routed automatically to all holders of role <b>{s.assignee.role_code}</b> ({s.candidates.map((c: any) => c.full_name).join(', ') || 'none found'})</Text>}
                {s.assignee.kind === 'pick' && !s.skipped && (
                  <MultiSelect mt={6} searchable placeholder={s.candidates.length ? 'Choose from eligible people' : 'No eligible person in scope — contact your administrator'} value={picks[s.key] || []} maxValues={s.assignee.max || undefined}
                    onChange={(v) => setPicks({ ...picks, [s.key]: v })} data={s.candidates.map((c: any) => ({ value: c.id, label: `${c.full_name}${c.designation ? ' — ' + c.designation : ''}` }))}
                    description={`${s.assignee.role_code ? `Eligible role: ${s.assignee.role_code}. ` : ''}Select ${s.assignee.min}${s.assignee.max ? `–${s.assignee.max}` : '+'}.${s.sla_hours ? ` SLA ${s.sla_hours} h.` : ''}`} />
                )}
              </Timeline.Item>
            ))}
          </Timeline>
          <Textarea label="Note to reviewers (optional)" autosize minRows={2} value={comment} onChange={(e) => setComment(e.currentTarget.value)} />
          <Group justify="flex-end"><Button variant="default" onClick={onClose}>Cancel</Button><Button leftSection={<IconSend size={16} />} disabled={!ready} loading={act.isPending} onClick={() => act.mutate(undefined)}>Submit</Button></Group>
        </Stack>
      )}
    </Modal>
  )
}

function ReleaseModal({ opened, onClose, d }: { opened: boolean; onClose: () => void; d: DocFull }) {
  const checks = useQuery<any[]>({ queryKey: ['release-checks', d.id], queryFn: () => api.get(`/documents/${d.id}/release-checks`), enabled: opened })
  const [note, setNote] = useState('')
  const act = useAction(() => api.post(`/documents/${d.id}/release`, { note }), { success: (r: any) => `Released as ${r.release_no}`, invalidate: [['doc', d.id], ['documents'], ['dashboard'], ['register']], onDone: onClose })
  const ok = checks.data?.every((c) => c.ok)
  return (
    <Modal opened={opened} onClose={onClose} size={560} title={<Text fw={650} size="lg">Release {d.number} rev {d.current_revision?.label}</Text>}>
      <Stack>
        <Text size="sm" c="dimmed">The release gate is checked again on the server. Once released, this revision is immutable and appears in the Central Release Register.</Text>
        {checks.isLoading ? <Loader size="sm" /> : (checks.data || []).map((c) => (
          <Group key={c.key} gap={8}>{c.ok ? <ThemeIcon size={22} radius="xl" color="teal"><IconCheck size={14} /></ThemeIcon> : <ThemeIcon size={22} radius="xl" color="red"><IconX size={14} /></ThemeIcon>}<Text size="sm">{c.label}</Text></Group>
        ))}
        <Textarea label="Release note" value={note} onChange={(e) => setNote(e.currentTarget.value)} autosize minRows={2} />
        <Group justify="flex-end"><Button variant="default" onClick={onClose}>Cancel</Button><Button color="teal" leftSection={<IconCertificate size={16} />} disabled={!ok} loading={act.isPending} onClick={() => act.mutate(undefined)}>Release</Button></Group>
      </Stack>
    </Modal>
  )
}

function UploadModal({ opened, onClose, d }: { opened: boolean; onClose: () => void; d: DocFull }) {
  const [file, setFile] = useState<File | null>(null)
  const [note, setNote] = useState('')
  const act = useAction(() => { const fd = new FormData(); fd.append('file', file!); if (note) fd.append('note', note); return api.post(`/documents/${d.id}/content`, fd) }, {
    success: 'New iteration saved — previous content is kept in history', invalidate: [['doc', d.id]], onDone: () => { setFile(null); onClose() },
  })
  return (
    <Modal opened={opened} onClose={onClose} title="Upload new content">
      <Stack>
        <Dropzone onDrop={(f) => setFile(f[0])} multiple={false}>
          <Group justify="center" mih={110} style={{ pointerEvents: 'none' }}><IconCloudUpload size={36} color="#94a3b8" /><div><Text fw={600}>{file ? file.name : 'Drop file or click to browse'}</Text><Text size="xs" c="dimmed">Allowed for {d.type.code}: see document type configuration</Text></div></Group>
        </Dropzone>
        <TextInput label="What changed?" value={note} onChange={(e) => setNote(e.currentTarget.value)} />
        <Group justify="flex-end"><Button variant="default" onClick={onClose}>Cancel</Button><Button disabled={!file} loading={act.isPending} onClick={() => act.mutate(undefined)}>Upload</Button></Group>
      </Stack>
    </Modal>
  )
}

function ReviseModal({ opened, onClose, d }: { opened: boolean; onClose: () => void; d: DocFull }) {
  const [summary, setSummary] = useState('')
  const act = useAction(() => api.post(`/documents/${d.id}/revise`, { change_summary: summary }), { success: (r: any) => `Revision ${r.label} started from the released content`, invalidate: [['doc', d.id], ['doc-wf', d.id], ['documents']], onDone: onClose })
  return (
    <Modal opened={opened} onClose={onClose} title="Start a new revision">
      <Stack>
        <Text size="sm" c="dimmed">The released revision stays untouched in the register. A new draft revision is created as a copy for you to change.</Text>
        <Textarea label="Reason for change / change summary" required autosize minRows={3} value={summary} onChange={(e) => setSummary(e.currentTarget.value)} placeholder="e.g. Incorporate CDR action items 12–18; ECR ALPHA-ECR-2026-0004" />
        <Group justify="flex-end"><Button variant="default" onClick={onClose}>Cancel</Button><Button disabled={summary.length < 3} loading={act.isPending} onClick={() => act.mutate(undefined)}>Create revision</Button></Group>
      </Stack>
    </Modal>
  )
}

function ShareModal({ opened, onClose, d }: { opened: boolean; onClose: () => void; d: DocFull }) {
  const orgs = useOrgUnits()
  const [kind, setKind] = useState<string | null>('user')
  const [userId, setUserId] = useState<string | null>(null)
  const [orgId, setOrgId] = useState<string | null>(null)
  const [perms, setPerms] = useState<string[]>(['view'])
  const [until, setUntil] = useState<Date | null>(null)
  const [reason, setReason] = useState('')
  const act = useAction(() => api.post(`/documents/${d.id}/grants`, { user_id: kind === 'user' ? userId : undefined, org_unit_id: kind === 'org' ? orgId : undefined, permissions: perms, valid_to: until?.toISOString(), reason }), { success: 'Access granted and recorded', invalidate: [['doc', d.id]], onDone: onClose })
  return (
    <Modal opened={opened} onClose={onClose} title="Share document">
      <Stack>
        <Select label="Share with" value={kind} onChange={setKind} data={[{ value: 'user', label: 'A person' }, { value: 'org', label: 'A directorate / department' }]} />
        {kind === 'user' ? <UserSelect label="Person" value={userId} onChange={setUserId} required /> : <Select label="Organization unit" searchable value={orgId} onChange={setOrgId} data={(orgs.data || []).map((o) => ({ value: o.id, label: `${o.code} — ${o.name}` }))} />}
        <MultiSelect label="Permissions" value={perms} onChange={setPerms} data={[{ value: 'view', label: 'View' }, { value: 'download', label: 'Download' }, { value: 'comment', label: 'Comment' }, { value: 'edit', label: 'Edit drafts' }]} />
        <DateInput label="Access expires (optional)" value={until} onChange={setUntil} clearable minDate={new Date()} />
        <TextInput label="Reason" required value={reason} onChange={(e) => setReason(e.currentTarget.value)} placeholder="e.g. Cross-directorate interface review" />
        <Group justify="flex-end"><Button variant="default" onClick={onClose}>Cancel</Button><Button disabled={reason.length < 3 || (kind === 'user' ? !userId : !orgId)} loading={act.isPending} onClick={() => act.mutate(undefined)}>Share</Button></Group>
      </Stack>
    </Modal>
  )
}

function RelateModal({ opened, onClose, d }: { opened: boolean; onClose: () => void; d: DocFull }) {
  const [q, setQ] = useState('')
  const [target, setTarget] = useState<string | null>(null)
  const [type, setType] = useState<string | null>('REFERENCES')
  const res = useQuery({ queryKey: ['search', q], queryFn: () => api.get('/search', { q }), enabled: q.length >= 2 })
  const act = useAction(() => api.post(`/documents/${d.id}/relations`, { target_id: target, relation_type: type }), { success: 'Relation added', invalidate: [['doc', d.id]], onDone: onClose })
  return (
    <Modal opened={opened} onClose={onClose} title="Link a related document">
      <Stack>
        <Select label="Relation" value={type} onChange={setType} data={[{ value: 'PARENT_OF', label: 'is parent of →' }, { value: 'DERIVED_FROM', label: 'is derived from →' }, { value: 'REFERENCES', label: 'references →' }, { value: 'SUPERSEDES', label: 'supersedes →' }, { value: 'RELATED', label: 'is related to' }]} />
        <Select label="Document" searchable onSearchChange={setQ} filter={({ options }) => options} value={target} onChange={setTarget} nothingFoundMessage={q.length < 2 ? 'Type to search' : 'No match'}
          data={(res.data?.documents || []).filter((x: any) => x.id !== d.id).map((x: any) => ({ value: x.id, label: `${x.number} — ${x.title}` }))} />
        <Group justify="flex-end"><Button variant="default" onClick={onClose}>Cancel</Button><Button disabled={!target} loading={act.isPending} onClick={() => act.mutate(undefined)}>Link</Button></Group>
      </Stack>
    </Modal>
  )
}

// ---------------------------------------------------------------- tabs
function ReviewHistory({ runs }: { runs: any[] }) {
  if (!runs.length) return <EmptyBlock text="Not submitted for review yet." />
  return (
    <Stack>
      {runs.map((r) => (
        <Card key={r.id} withBorder p="md">
          <Group justify="space-between" mb="xs"><Text fw={600}>Cycle {r.cycle_no} · rev {r.revision.label}.{r.iteration} · {r.workflow.name} v{r.workflow.version_no}</Text><Group gap={8}><StatusTag status={r.status} /><Text size="xs" c="dimmed"><When at={r.started_at} /></Text></Group></Group>
          <Timeline bulletSize={20} lineWidth={2}>
            {r.stages.flatMap((s: any) => s.tasks.filter((t: any) => t.status !== 'PENDING' && t.status !== 'CANCELLED').map((t: any) => (
              <Timeline.Item key={t.id} color={t.status === 'APPROVED' || t.status === 'SIGNED' ? 'teal' : t.status === 'REASSIGNED' ? 'gray' : 'red'} title={<Group gap={6}><Text size="sm" fw={600}>{s.name}</Text><StatusTag status={t.status} /></Group>}>
                <Text size="sm">{t.acted_by ? `${t.acted_by.full_name} on behalf of ${t.assignee.full_name}` : t.assignee.full_name} · <When at={t.acted_at} /></Text>
                {t.comment && <Text size="sm" c="dimmed">“{t.comment}”</Text>}
              </Timeline.Item>
            )))}
          </Timeline>
          <Text size="xs" c="dimmed" mt="xs" component="div">Bound to SHA-256 <Hash value={r.sha256} /></Text>
        </Card>
      ))}
    </Stack>
  )
}

function Revisions({ d }: { d: DocFull }) {
  return (
    <Grid>
      <Grid.Col span={{ base: 12, lg: 7 }}>
        <Text fw={600} mb="xs">Revisions</Text>
        <Table>
          <Table.Thead><Table.Tr><Table.Th>Rev</Table.Th><Table.Th>Status</Table.Th><Table.Th>Change</Table.Th><Table.Th>By</Table.Th><Table.Th>Released</Table.Th><Table.Th /></Table.Tr></Table.Thead>
          <Table.Tbody>
            {d.revisions.map((r) => (
              <Table.Tr key={r.id}>
                <Table.Td><Badge color="dark">{r.label}</Badge></Table.Td><Table.Td><StatusTag status={r.status} locked={r.locked} /></Table.Td>
                <Table.Td><Text size="sm" lineClamp={2}>{r.change_summary}</Text></Table.Td><Table.Td><UserAvatar user={r.created_by} size={22} /></Table.Td>
                <Table.Td><Text size="xs">{r.released_at ? new Date(r.released_at).toLocaleDateString() : '—'}</Text></Table.Td>
                <Table.Td>{r.file && d.permissions.download && <Button size="compact-xs" variant="subtle" component="a" href={fileUrl(d.id, r.id, false)} leftSection={<IconDownload size={12} />}>{fmtSize(r.file.size)}</Button>}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Grid.Col>
      <Grid.Col span={{ base: 12, lg: 5 }}>
        <Text fw={600} mb="xs">Saved iterations of rev {d.current_revision?.label} <Text span size="xs" c="dimmed">(nothing is overwritten)</Text></Text>
        <Timeline bulletSize={18}>
          {d.iterations.map((i) => (
            <Timeline.Item key={i.iteration} title={<Group gap={6}><Text size="sm" fw={600}>.{i.iteration}</Text><Badge size="xs" color="gray">{i.source.toLowerCase()}</Badge><Text size="xs" c="dimmed">{fmtSize(i.size)}</Text></Group>}>
              <Text size="xs">{i.by?.full_name} · <When at={i.created_at} /></Text>
              {i.note && <Text size="xs" c="dimmed">{i.note}</Text>}
              <Group gap={4}><Hash value={i.sha256} />{d.permissions.download && <Tooltip label="Download this iteration"><Button size="compact-xs" variant="subtle" component="a" href={fileUrl(d.id, d.current_revision!.id, false, i.iteration)}><IconDownload size={12} /></Button></Tooltip>}</Group>
            </Timeline.Item>
          ))}
        </Timeline>
      </Grid.Col>
    </Grid>
  )
}

function Signatures({ d }: { d: DocFull }) {
  const [res, setRes] = useState<Record<string, any>>({})
  const verify = async (sid: string) => {
    try { const r = await api.get(`/documents/${d.id}/signatures/${sid}/verify`); setRes((x) => ({ ...x, [sid]: r })) } catch (e) { notifications.show({ color: 'red', message: errorText(e) }) }
  }
  if (!d.signatures.length) return <EmptyBlock text="No signatures yet. Signatures are requested automatically after approval." icon={<IconRosetteDiscountCheck size={26} />} />
  const revLabel = (id: string) => d.revisions.find((r) => r.id === id)?.label
  return (
    <Table>
      <Table.Thead><Table.Tr><Table.Th>Signer</Table.Th><Table.Th>Signed as</Table.Th><Table.Th>Rev</Table.Th><Table.Th>Certificate</Table.Th><Table.Th>Signed</Table.Th><Table.Th>Validation</Table.Th></Table.Tr></Table.Thead>
      <Table.Tbody>
        {d.signatures.map((s) => (
          <Table.Tr key={s.id}>
            <Table.Td><UserAvatar user={s.signer} showName /></Table.Td>
            <Table.Td><Badge color="yellow">{s.role}</Badge></Table.Td>
            <Table.Td>{revLabel(s.revision_id)}</Table.Td>
            <Table.Td><Text size="xs">{s.subject}</Text><Text size="xs" c="dimmed">serial {s.serial} · {s.algorithm} · {s.provider}{!s.is_cryptographic && ' (electronic approval)'}</Text></Table.Td>
            <Table.Td><Text size="xs"><When at={s.signed_at} /></Text></Table.Td>
            <Table.Td>{res[s.id] ? <Tooltip label={res[s.id].reason}><Badge color={res[s.id].valid ? 'teal' : 'red'} leftSection={res[s.id].valid ? <IconCheck size={12} /> : <IconX size={12} />}>{res[s.id].valid ? 'Valid' : 'Invalid'}</Badge></Tooltip>
              : <Button size="compact-xs" variant="light" leftSection={<IconShieldCheck size={12} />} onClick={() => verify(s.id)}>Verify now</Button>}</Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  )
}

function Relations({ d }: { d: DocFull }) {
  const nav = useNavigate()
  const { nodes, edges } = useMemo(() => {
    const nodes: Node[] = [{ id: d.id, position: { x: 340, y: 160 }, data: { label: <div><b>{d.number}</b><br /><span style={{ fontSize: 11 }}>{d.title.slice(0, 40)}</span></div> }, style: { border: '2px solid #2563eb', borderRadius: 10, width: 220 } }]
    const edges: Edge[] = []
    const ins = d.relations.filter((r) => r.direction === 'in')
    const outs = d.relations.filter((r) => r.direction === 'out')
    ins.forEach((r, i) => { nodes.push({ id: r.document.id, position: { x: 20, y: 40 + i * 110 }, data: { label: <div><b>{r.document.number}</b><br /><span style={{ fontSize: 11 }}>{r.document.title?.slice(0, 36)}</span></div> }, style: { borderRadius: 10, width: 220 } }); edges.push({ id: r.id, source: r.document.id, target: d.id, label: r.relation_type.replace('_', ' ').toLowerCase(), animated: true }) })
    outs.forEach((r, i) => { nodes.push({ id: r.document.id, position: { x: 660, y: 40 + i * 110 }, data: { label: <div><b>{r.document.number}</b><br /><span style={{ fontSize: 11 }}>{r.document.title?.slice(0, 36)}</span></div> }, style: { borderRadius: 10, width: 220 } }); edges.push({ id: r.id, source: d.id, target: r.document.id, label: r.relation_type.replace('_', ' ').toLowerCase(), animated: true }) })
    return { nodes, edges }
  }, [d])
  if (!d.relations.length) return <EmptyBlock text="No related documents. Link parents, children, references or superseded documents for traceability." />
  return (
    <div style={{ height: Math.max(360, 120 + d.relations.length * 70), border: '1px solid var(--elm-border)', borderRadius: 12 }}>
      <ReactFlow nodes={nodes} edges={edges} fitView onNodeClick={(_, n) => n.id !== d.id && !d.relations.find((r) => r.document.id === n.id)?.document.restricted && nav(`/documents/${n.id}`)} proOptions={{ hideAttribution: true }}>
        <Background gap={18} /><Controls showInteractive={false} />
      </ReactFlow>
    </div>
  )
}

function Discussion({ docId }: { docId: string }) {
  const { data, refetch } = useQuery<any[]>({ queryKey: ['comments', docId], queryFn: () => api.get(`/documents/${docId}/comments`) })
  const [body, setBody] = useState('')
  const [anchor, setAnchor] = useState('')
  const add = useAction(() => api.post(`/documents/${docId}/comments`, { body, anchor: anchor || undefined }), { onDone: () => { setBody(''); setAnchor(''); refetch() } })
  const resolve = async (id: string) => { await api.post(`/documents/${docId}/comments/${id}/resolve`); refetch() }
  return (
    <Grid>
      <Grid.Col span={{ base: 12, lg: 8 }}>
        <Stack gap="sm">
          {!data?.length && <EmptyBlock text="No comments yet." />}
          {data?.map((c) => (
            <Card key={c.id} withBorder p="sm" style={{ opacity: c.resolved ? 0.6 : 1 }}>
              <Group justify="space-between"><Group gap={8}><UserAvatar user={c.author} size={26} /><Text size="sm" fw={600}>{c.author.full_name}</Text>{c.revision && <Badge size="xs" color="gray">rev {c.revision}</Badge>}{c.anchor && <Badge size="xs" variant="outline">§ {c.anchor}</Badge>}</Group>
                <Group gap={8}><Text size="xs" c="dimmed"><When at={c.created_at} /></Text><Button size="compact-xs" variant={c.resolved ? 'light' : 'subtle'} color="teal" onClick={() => resolve(c.id)}>{c.resolved ? 'Resolved' : 'Resolve'}</Button></Group></Group>
              <Text size="sm" mt={6} style={{ whiteSpace: 'pre-wrap' }}>{c.body}</Text>
            </Card>
          ))}
        </Stack>
      </Grid.Col>
      <Grid.Col span={{ base: 12, lg: 4 }}>
        <Card withBorder>
          <Text fw={600} mb="xs">Add comment</Text>
          <TextInput size="xs" placeholder="Section / page / requirement (optional)" value={anchor} onChange={(e) => setAnchor(e.currentTarget.value)} mb="xs" />
          <Textarea autosize minRows={4} value={body} onChange={(e) => setBody(e.currentTarget.value)} placeholder="Write a comment…" />
          <Button mt="sm" fullWidth disabled={!body.trim()} loading={add.isPending} onClick={() => add.mutate(undefined)}>Post</Button>
        </Card>
      </Grid.Col>
    </Grid>
  )
}

function Access({ d, onShare }: { d: DocFull; onShare: () => void }) {
  const revoke = useAction((gid: string) => api.del(`/documents/${d.id}/grants/${gid}`), { success: 'Access revoked', invalidate: [['doc', d.id]] })
  return (
    <Stack>
      <Alert variant="light" color="gray">Default access is <b>deny</b>. People see this document through their scoped roles (project / directorate / item), workflow assignments, the Release Register (released revisions only), or the explicit shares below.</Alert>
      <Group justify="space-between"><Text fw={600}>Explicit shares</Text>{d.permissions.share && <Button size="xs" leftSection={<IconShare size={14} />} onClick={onShare}>Share</Button>}</Group>
      {!d.grants.length ? <EmptyBlock text="Not shared explicitly." /> : (
        <Table>
          <Table.Thead><Table.Tr><Table.Th>With</Table.Th><Table.Th>Permissions</Table.Th><Table.Th>Until</Table.Th><Table.Th>Reason</Table.Th><Table.Th>By</Table.Th><Table.Th /></Table.Tr></Table.Thead>
          <Table.Tbody>{d.grants.map((g) => (
            <Table.Tr key={g.id}>
              <Table.Td>{g.user ? <UserAvatar user={g.user} showName /> : <Text size="sm"><b>{g.org?.code}</b> {g.org?.name}</Text>}</Table.Td>
              <Table.Td><Group gap={4}>{g.permissions.map((p) => <Badge key={p} size="xs">{p}</Badge>)}</Group></Table.Td>
              <Table.Td>{g.valid_to ? new Date(g.valid_to).toLocaleDateString() : 'No expiry'}</Table.Td><Table.Td><Text size="sm">{g.reason}</Text></Table.Td>
              <Table.Td><UserAvatar user={g.granted_by} size={22} /></Table.Td>
              <Table.Td>{d.permissions.share && <Button size="compact-xs" color="red" variant="subtle" onClick={() => revoke.mutate(g.id)}>Revoke</Button>}</Table.Td>
            </Table.Tr>
          ))}</Table.Tbody>
        </Table>
      )}
      {!!d.releases.length && <>
        <Text fw={600} mt="md">Release register entries</Text>
        <Table><Table.Tbody>{d.releases.map((e) => (
          <Table.Tr key={e.id}><Table.Td><b>{e.release_no}</b></Table.Td><Table.Td><StatusTag status={e.status} /></Table.Td><Table.Td>{d.revisions.find((r) => r.id === e.revision_id)?.label}</Table.Td><Table.Td><When at={e.released_at} /></Table.Td><Table.Td><UserAvatar user={e.by} showName /></Table.Td><Table.Td><Hash value={e.sha256} /></Table.Td></Table.Tr>
        ))}</Table.Tbody></Table>
      </>}
    </Stack>
  )
}

function AuditTab({ docId }: { docId: string }) {
  const { data } = useQuery<any[]>({ queryKey: ['doc-history', docId], queryFn: () => api.get(`/documents/${docId}/history`) })
  return (
    <Timeline bulletSize={14} lineWidth={2}>
      {(data || []).map((e) => (
        <Timeline.Item key={e.seq} color={e.outcome !== 'SUCCESS' ? 'red' : e.action.startsWith('release') ? 'teal' : e.action.startsWith('signature') ? 'yellow' : 'blue'} title={<Text size="sm">{e.summary}</Text>}>
          <Text size="xs" c="dimmed">{e.actor?.full_name || 'System'} · {new Date(e.at).toLocaleString()} · #{e.seq} · <span className="hash">{e.hash.slice(0, 12)}</span></Text>
        </Timeline.Item>
      ))}
    </Timeline>
  )
}
