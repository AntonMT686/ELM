import { Badge, Button, Card, ColorInput, Drawer, Group, Select, Stack, Switch, Table, TagsInput, Text, TextInput, Textarea } from '@mantine/core'
import { IconFileDescription, IconPlus } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import { useAction, useDocTypes } from '../../api/hooks'
import { PageTitle } from '../../components/common'

export default function DocTypesPage() {
  const { data = [] } = useDocTypes()
  const [sel, setSel] = useState<any | null>(null)
  return (
    <div className="page">
      <PageTitle icon={<IconFileDescription size={22} />} title="Document types" sub="Numbering, revision scheme, formats, templates, signature requirement and applicable breakdown levels."
        extra={<Button leftSection={<IconPlus size={16} />} onClick={() => setSel({})}>New type</Button>} />
      <Card p={0}>
        <Table>
          <Table.Thead><Table.Tr><Table.Th>Type</Table.Th><Table.Th>Category</Table.Th><Table.Th>Numbering</Table.Th><Table.Th>Formats</Table.Th><Table.Th>Levels</Table.Th><Table.Th>Signature</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>
            {data.map((t) => (
              <Table.Tr key={t.id} className="clickable" onClick={() => setSel(t)} style={{ opacity: t.active ? 1 : 0.5 }}>
                <Table.Td><Group gap={8}><span className="lvl" style={{ background: t.color || '#64748b' }}>{t.code}</span><Text size="sm" fw={550}>{t.name}</Text></Group></Table.Td>
                <Table.Td><Badge color="gray">{t.category.replace('_', ' ').toLowerCase()}</Badge></Table.Td>
                <Table.Td><code style={{ fontSize: 12 }}>{t.numbering_pattern}</code></Table.Td>
                <Table.Td><Text size="xs">{t.allowed_extensions}</Text></Table.Td>
                <Table.Td><Text size="xs">{t.applicable_levels || 'any'}</Text></Table.Td>
                <Table.Td>{t.requires_signature ? <Badge color="yellow">required</Badge> : <Badge color="gray">no</Badge>}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>
      <TypeDrawer t={sel} onClose={() => setSel(null)} />
    </div>
  )
}

function TypeDrawer({ t, onClose }: { t: any | null; onClose: () => void }) {
  const [f, setF] = useState<any>({})
  useEffect(() => { if (t) setF({ code: '', name: '', category: 'ENGINEERING', numbering_pattern: '{PROJECT}-{ITEM}-{TYPE}-{SEQ:3}', revision_scheme: 'ALPHA', allowed_extensions: 'docx,pdf', default_template: 'docx', requires_signature: true, require_review_checklist: false, applicable_levels: '', color: '#2563eb', active: true, description: '', ...t }) }, [t])
  const save = useAction(() => api.post('/document-types', { ...f, applicable_levels: f.applicable_levels || null, default_template: f.default_template || null }), { success: 'Document type saved', invalidate: [['doc-types']], onDone: onClose })
  const set = (k: string) => (v: any) => setF({ ...f, [k]: v })
  return (
    <Drawer opened={!!t} onClose={onClose} position="right" size={480} title={<Text fw={650}>{t?.id ? `Edit ${t.code}` : 'New document type'}</Text>}>
      <Stack>
        <Group grow><TextInput label="Code" disabled={!!t?.id} value={f.code} onChange={(e) => set('code')(e.currentTarget.value.toUpperCase())} /><ColorInput label="Colour" value={f.color} onChange={set('color')} /></Group>
        <TextInput label="Name" value={f.name} onChange={(e) => set('name')(e.currentTarget.value)} />
        <Select label="Category" value={f.category} onChange={set('category')} data={[{ value: 'ENGINEERING', label: 'Engineering' }, { value: 'MANAGEMENT', label: 'Programme / management' }, { value: 'NON_ENGINEERING', label: 'Non-engineering / administrative' }]} />
        <TextInput label="Numbering pattern" description="Tokens: {PROJECT} {ITEM} {TYPE} {ORG} {YEAR} {SEQ:n}" value={f.numbering_pattern} onChange={(e) => set('numbering_pattern')(e.currentTarget.value)} />
        <Group grow>
          <Select label="Revision scheme" value={f.revision_scheme} onChange={set('revision_scheme')} data={[{ value: 'ALPHA', label: 'A, B, C …' }, { value: 'NUMERIC', label: '01, 02 …' }]} />
          <Select label="Template" clearable value={f.default_template || null} onChange={set('default_template')} data={['docx', 'xlsx', 'pptx']} />
        </Group>
        <TagsInput label="Allowed file extensions" value={(f.allowed_extensions || '').split(',').filter(Boolean)} onChange={(v) => set('allowed_extensions')(v.join(','))} />
        <TagsInput label="Applicable breakdown levels" description="Empty = any level (e.g. SYSTEM, UNIT)" value={(f.applicable_levels || '').split(',').filter(Boolean)} onChange={(v) => set('applicable_levels')(v.map((x) => x.toUpperCase()).join(','))} />
        <Textarea label="Description" value={f.description || ''} onChange={(e) => set('description')(e.currentTarget.value)} />
        <Switch label="Digital signature required before release" checked={f.requires_signature} onChange={(e) => set('requires_signature')(e.currentTarget.checked)} />
        <Switch label="Preparer must write a review checklist before submitting" description="Reviewers and approvers then answer every item OK / Not OK / N/A" checked={!!f.require_review_checklist} onChange={(e) => set('require_review_checklist')(e.currentTarget.checked)} />
        <Switch label="Active" checked={f.active} onChange={(e) => set('active')(e.currentTarget.checked)} />
        <Button loading={save.isPending} disabled={f.code?.length < 2 || !f.name} onClick={() => save.mutate(undefined)}>Save</Button>
      </Stack>
    </Drawer>
  )
}
