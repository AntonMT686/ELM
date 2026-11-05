import { Alert, Center, Loader, Stack, Text } from '@mantine/core'
import { useComputedColorScheme } from '@mantine/core'
import { IconAlertTriangle, IconLock } from '@tabler/icons-react'
import { useEffect, useRef, useState } from 'react'
import { api, errorText } from '../api/client'

declare global {
  interface Window { DocsAPI?: any }
}

const loaded: Record<string, Promise<void>> = {}
function loadApi(server: string): Promise<void> {
  // api.js is served by the self-hosted OnlyOffice Document Server on the intranet (not a public CDN).
  const src = `${server}/web-apps/apps/api/documents/api.js`
  if (!loaded[src]) {
    loaded[src] = new Promise((resolve, reject) => {
      const s = document.createElement('script')
      s.src = src
      s.async = true
      s.onload = () => resolve()
      s.onerror = () => { delete loaded[src]; reject(new Error('Document Server is not reachable. Check that the OnlyOffice container is running and ELM_ONLYOFFICE_PUBLIC_URL is correct.')) }
      document.body.appendChild(s)
    })
  }
  return loaded[src]
}

interface Props { revisionId: string; mode?: 'edit' | 'view'; height?: number | string; onModeResolved?: (m: string) => void }

export default function OnlyOfficeEditor({ revisionId, mode = 'view', height = '100%', onModeResolved }: Props) {
  const holder = useRef(`oo-${Math.random().toString(36).slice(2)}`)
  const scheme = useComputedColorScheme('light')
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [err, setErr] = useState('')
  const [effective, setEffective] = useState<string>()

  useEffect(() => {
    let editor: any
    let cancelled = false
    setState('loading')
    api.get(`/onlyoffice/config/${revisionId}`, { mode })
      .then(async (cfg) => {
        await loadApi(cfg.documentServerUrl)
        if (cancelled) return
        setEffective(cfg.mode)
        onModeResolved?.(cfg.mode)
        const conf = {
          ...cfg.config,
          editorConfig: { ...cfg.config.editorConfig, customization: { ...cfg.config.editorConfig.customization, uiTheme: scheme === 'dark' ? 'theme-dark' : 'theme-light' } },
          events: { onAppReady: () => setState('ready'), onError: (e: any) => { setErr(e?.data?.errorDescription || 'Editor error'); setState('error') } },
        }
        editor = new window.DocsAPI!.DocEditor(holder.current, conf)
        setTimeout(() => !cancelled && setState((s) => (s === 'loading' ? 'ready' : s)), 8000)
      })
      .catch((e) => { if (!cancelled) { setErr(errorText(e)); setState('error') } })
    return () => { cancelled = true; try { editor?.destroyEditor?.() } catch { /* noop */ } }
  }, [revisionId, mode])

  if (state === 'error')
    return (
      <Center h={height} p="xl">
        <Stack align="center" gap={6} maw={480}>
          <IconAlertTriangle size={40} color="#d97706" />
          <Text fw={600}>Document editor unavailable</Text>
          <Text c="dimmed" size="sm" ta="center">{err}</Text>
        </Stack>
      </Center>
    )
  return (
    <div style={{ position: 'relative', height, width: '100%', display: 'flex', flexDirection: 'column' }}>
      {state === 'loading' && <Center pos="absolute" inset={0} style={{ zIndex: 1 }}><Stack align="center" gap={6}><Loader /><Text size="sm" c="dimmed">Opening document…</Text></Stack></Center>}
      {effective === 'view' && mode === 'edit' && <Alert radius={0} color="blue" icon={<IconLock size={16} />} p={8}>This revision is locked (under review or released) — opened read-only.</Alert>}
      <div id={holder.current} style={{ flex: 1 }} />
    </div>
  )
}
