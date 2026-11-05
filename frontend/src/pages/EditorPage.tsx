import { Badge, Button, Center, Loader, Text } from '@mantine/core'
import { IconArrowLeft, IconSend } from '@tabler/icons-react'
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useDoc } from '../api/hooks'
import { StatusTag, TypeBadge } from '../components/common'
import OnlyOfficeEditor from '../components/OnlyOfficeEditor'

/** Full-screen OnlyOffice authoring. Saves are stored by the backend as new iterations of the draft revision. */
export default function EditorPage() {
  const { id } = useParams()
  const nav = useNavigate()
  const qc = useQueryClient()
  const { data: d } = useDoc(id)
  const [mode, setMode] = useState<string>()
  if (!d) return <Center h="100vh"><Loader /></Center>
  const rev = d.current_revision_full!
  const back = () => { qc.invalidateQueries({ queryKey: ['doc', id] }); nav(`/documents/${id}`) }
  return (
    <div className="editor-frame">
      <div className="editor-bar">
        <Button variant="subtle" leftSection={<IconArrowLeft size={16} />} onClick={back}>Back</Button>
        <TypeBadge type={d.type} />
        <Text fw={650}>{d.number}</Text>
        <Badge color="dark">Rev {rev.label}</Badge>
        <StatusTag status={d.status} locked={rev.locked} />
        <Text c="dimmed" size="sm" truncate style={{ flex: 1 }}>{d.title}</Text>
        {mode === 'edit' && <Text size="xs" c="dimmed">Changes are auto-saved to a new iteration when you close the editor.</Text>}
        {d.permissions.submit && <Button size="xs" leftSection={<IconSend size={14} />} onClick={() => { back() }}>Done — go submit</Button>}
      </div>
      <div style={{ flex: 1 }}>
        <OnlyOfficeEditor revisionId={rev.id} mode="edit" onModeResolved={setMode} />
      </div>

    </div>
  )
}
