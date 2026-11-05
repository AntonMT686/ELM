import { ActionIcon, Center, Group, Loader, Text } from '@mantine/core'
import { IconMinus, IconPlus } from '@tabler/icons-react'
import * as pdfjs from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { useEffect, useRef, useState } from 'react'

// Locally bundled PDF.js worker — no CDN.
pdfjs.GlobalWorkerOptions.workerSrc = workerUrl

export default function PdfViewer({ url, height = 640 }: { url: string; height?: number | string }) {
  const box = useRef<HTMLDivElement>(null)
  const [doc, setDoc] = useState<any>(null)
  const [scale, setScale] = useState(1.15)
  const [err, setErr] = useState('')

  useEffect(() => {
    setDoc(null)
    const task = pdfjs.getDocument({ url, withCredentials: true, isEvalSupported: false })
    task.promise.then(setDoc).catch((e: any) => setErr(e?.message || 'Unable to open PDF'))
    return () => { task.destroy() }
  }, [url])

  useEffect(() => {
    if (!doc || !box.current) return
    const el = box.current
    el.innerHTML = ''
    let stop = false
    ;(async () => {
      for (let i = 1; i <= doc.numPages && !stop; i++) {
        const page = await doc.getPage(i)
        const vp = page.getViewport({ scale })
        const canvas = document.createElement('canvas')
        const ratio = window.devicePixelRatio || 1
        canvas.width = vp.width * ratio
        canvas.height = vp.height * ratio
        canvas.style.width = `${vp.width}px`
        canvas.className = 'pdf-page'
        el.appendChild(canvas)
        const ctx = canvas.getContext('2d')!
        ctx.scale(ratio, ratio)
        await page.render({ canvasContext: ctx, viewport: vp }).promise
      }
    })()
    return () => { stop = true }
  }, [doc, scale])

  if (err) return <Center h={200}><Text c="dimmed">Preview unavailable: {err}</Text></Center>
  return (
    <div style={{ height, display: 'flex', flexDirection: 'column', background: 'var(--elm-soft)', borderRadius: 10 }}>
      <Group justify="flex-end" p={8} gap={6}>
        <Text size="xs" c="dimmed">{doc ? `${doc.numPages} page(s)` : ''}</Text>
        <ActionIcon variant="default" size="sm" onClick={() => setScale((s) => Math.max(0.5, s - 0.15))}><IconMinus size={14} /></ActionIcon>
        <Text size="xs" w={40} ta="center">{Math.round(scale * 100)}%</Text>
        <ActionIcon variant="default" size="sm" onClick={() => setScale((s) => Math.min(3, s + 0.15))}><IconPlus size={14} /></ActionIcon>
      </Group>
      <div style={{ overflow: 'auto', flex: 1, padding: 16 }}>
        {!doc && <Center py={60}><Loader /></Center>}
        <div ref={box} />
      </div>
    </div>
  )
}
