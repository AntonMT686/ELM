import { Alert, Button, Code, PasswordInput, Stack, Text, TextInput, Title } from '@mantine/core'
import { useForm } from '@mantine/form'
import { IconBinaryTree2, IconCertificate, IconLock, IconRosetteDiscountCheck, IconUser } from '@tabler/icons-react'
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { api, errorText } from '../api/client'
import { useMe } from '../api/hooks'

export default function LoginPage() {
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const nav = useNavigate()
  const [sp] = useSearchParams()
  const qc = useQueryClient()
  const session = useMe()
  const form = useForm({
    initialValues: { username: '', password: '' },
    validate: { username: (v) => (v.trim() ? null : 'Enter your username'), password: (v) => (v ? null : 'Enter your password') },
  })

  const submit = async (v: typeof form.values) => {
    setBusy(true)
    setErr('')
    try {
      await api.post('/auth/login', v)
      // Load the signed-in profile *before* navigating; otherwise the cached "not signed in"
      // result from the login screen bounces the user straight back to /login.
      const me = await api.get('/auth/me')
      qc.setQueryData(['me'], me)
      const next = sp.get('next')
      nav(next && next.startsWith('/') && !next.startsWith('/login') ? next : '/', { replace: true })
    } catch (e) {
      setErr(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  // Already signed in (valid session cookie) → go straight to the app.
  if (session.data) {
    const next = sp.get('next')
    return <Navigate to={next && next.startsWith('/') && !next.startsWith('/login') ? next : '/'} replace />
  }

  return (
    <div className="login-bg">
      <div className="login-art">
        <div className="grid" />
        <div style={{ position: 'relative', display: 'flex', alignItems: 'center', gap: 12 }}>
          <div className="brand-logo" style={{ width: 42, height: 42 }}><svg width="24" height="24" viewBox="0 0 64 64"><path d="M32 6 L37 27 L58 34 L37 39 L34 58 L29 58 L30 39 L8 36 L8 30 L30 27 Z" fill="#fff" /></svg></div>
          <div><div style={{ fontWeight: 700, fontSize: 18 }}>ADA · ELM</div><div style={{ opacity: 0.6, fontSize: 13 }}>Aeronautical Development Agency</div></div>
        </div>
        <div style={{ position: 'relative', maxWidth: 520 }}>
          <h1 style={{ fontSize: 40, lineHeight: 1.1, margin: 0, fontWeight: 700, letterSpacing: '-.02em' }}>One controlled thread from <span style={{ color: '#7dd3fc' }}>Aircraft</span> to every <span style={{ color: '#7dd3fc' }}>LRU</span>.</h1>
          <p style={{ opacity: 0.75, fontSize: 16, marginTop: 16 }}>Author, review, approve, sign and release engineering documents with complete traceability across directorates.</p>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 24 }}>
            <span className="chip"><IconBinaryTree2 size={15} /> Aircraft → System → LRU</span>
            <span className="chip"><IconRosetteDiscountCheck size={15} /> Digital signatures</span>
            <span className="chip"><IconCertificate size={15} /> Central release register</span>
          </div>
        </div>
        <div style={{ position: 'relative', opacity: 0.5, fontSize: 12 }}>Intranet system · Authorized users only · All actions are audited</div>
      </div>
      <div style={{ display: 'grid', placeItems: 'center', padding: 32 }}>
        <form onSubmit={form.onSubmit(submit)} style={{ width: '100%', maxWidth: 380 }}>
          <Stack gap="md">
            <div>
              <Title order={2}>Sign in</Title>
              <Text c="dimmed" size="sm">Use your ADA employee credentials.</Text>
            </div>
            {err && <Alert color="red" variant="light">{err}</Alert>}
            <TextInput size="md" label="Username" placeholder="e.g. pe.kumar" leftSection={<IconUser size={16} />} autoFocus autoComplete="username" {...form.getInputProps('username')} />
            <PasswordInput size="md" label="Password" leftSection={<IconLock size={16} />} autoComplete="current-password" {...form.getInputProps('password')} />
            <Button type="submit" size="md" fullWidth loading={busy}>Sign in</Button>
            {(import.meta.env.DEV || import.meta.env.VITE_DEMO_HINT === '1') && (
              <Alert variant="light" color="blue" mt="md">
                <Text size="xs"><b>Demo accounts</b> (password <Code>Elm@12345</Code>): pe.kumar · eng.priya · chk.das · rev.joshi · td.menon · cm.sharma · pgd.rao · dir.iyer · adm.babu · adm.head · proc.krishnan · qa.verma · admin</Text>
              </Alert>
            )}
          </Stack>
        </form>
      </div>
    </div>
  )
}
