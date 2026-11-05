import { Button, Center, Image } from '@mantine/core'
import { IconDownload } from '@tabler/icons-react'
import { lazy, Suspense } from 'react'
import { fileUrl } from '../api/client'
import { useMe } from '../api/hooks'
import { Notice } from './NotFound'
import OnlyOfficeEditor from './OnlyOfficeEditor'

const PdfViewer = lazy(() => import('./PdfViewer'))
const OFFICE = ['docx', 'xlsx', 'pptx', 'doc', 'xls', 'ppt', 'odt', 'ods', 'odp']

export default function DocumentPreview({ docId, revisionId, ext, height = 640 }: { docId: string; revisionId: string; ext?: string | null; height?: number | string }) {
  const { data: me } = useMe()
  if (!ext) return <Notice title="No content yet" text="Author the document from its template or upload a file to see a preview." />
  if (ext === 'pdf') return <Suspense fallback={null}><PdfViewer url={fileUrl(docId, revisionId, true)} height={height} /></Suspense>
  if (['png', 'jpg', 'jpeg'].includes(ext))
    return <Center p="md" bg="var(--elm-soft)" style={{ borderRadius: 10 }}><Image src={fileUrl(docId, revisionId, true)} mah={height as number} fit="contain" /></Center>
  if (OFFICE.includes(ext) && me?.settings.onlyoffice_enabled)
    return <div style={{ height, borderRadius: 10, overflow: 'hidden', border: '1px solid var(--elm-border)' }}><OnlyOfficeEditor key={revisionId} revisionId={revisionId} mode="view" /></div>
  return <Notice title={`.${ext} file`} text="Inline preview is not available for this format." action={<Button leftSection={<IconDownload size={16} />} component="a" href={fileUrl(docId, revisionId, false)}>Download</Button>} />
}
