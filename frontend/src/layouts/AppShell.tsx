import { ActionIcon, AppShell as MAppShell, Badge, Burger, Button, Drawer, Group, Indicator, Kbd, Menu, ScrollArea, SegmentedControl, Stack, Text, Tooltip, UnstyledButton, useMantineColorScheme } from '@mantine/core'
import { useDisclosure, useLocalStorage } from '@mantine/hooks'
import {
  IconAffiliate, IconBell, IconBinaryTree2, IconBuildingCommunity, IconCertificate, IconChecklist, IconFileDescription, IconFiles, IconFingerprint,
  IconGitBranch, IconHome, IconInbox, IconLayoutKanban, IconListCheck, IconLogout, IconMoon, IconRoute, IconSearch, IconShieldLock, IconSun, IconTimeline, IconUsers, IconUserCog,
} from '@tabler/icons-react'
import { useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { can, useMe, useNotifications } from '../api/hooks'
import CommandPalette, { openPalette } from '../components/CommandPalette'
import { UserAvatar, When } from '../components/common'
import ErrorBoundary from '../components/ErrorBoundary'

interface NavItem { to: string; label: string; icon: ReactNode; badge?: number; show?: boolean }

export default function AppShell() {
  const { data: me } = useMe()
  const nav = useNavigate()
  const loc = useLocation()
  const qc = useQueryClient()
  const { colorScheme, toggleColorScheme } = useMantineColorScheme()
  const [collapsed, setCollapsed] = useLocalStorage({ key: 'elm.sider', defaultValue: false })
  const [mobileOpen, mobile] = useDisclosure(false)
  const [bellOpen, bell] = useDisclosure(false)
  const notifs = useNotifications()

  const groups: { label: string; items: NavItem[] }[] = [
    { label: 'Work', items: [
      { to: '/', label: 'Home', icon: <IconHome size={19} /> },
      { to: '/inbox', label: 'Action inbox', icon: <IconInbox size={19} />, badge: me?.pending_tasks },
      { to: '/planning', label: 'Planning', icon: <IconTimeline size={19} /> },
      { to: '/tasks', label: 'Tasks board', icon: <IconLayoutKanban size={19} /> },
    ] },
    { label: 'Engineering', items: [
      { to: '/explorer', label: 'Product structure', icon: <IconBinaryTree2 size={19} /> },
      { to: '/requirements', label: 'Requirements', icon: <IconListCheck size={19} /> },
      { to: '/documents', label: 'Documents', icon: <IconFiles size={19} /> },
      { to: '/releases', label: 'Release register', icon: <IconCertificate size={19} /> },
    ] },
    { label: 'Governance', items: [
      { to: '/workflows', label: 'Workflow designer', icon: <IconGitBranch size={19} />, show: can(me, 'workflow.configure') },
      { to: '/admin/task-lifecycle', label: 'Task lifecycle', icon: <IconRoute size={19} />, show: can(me, 'workflow.configure') },
      { to: '/audit', label: 'Audit trail', icon: <IconFingerprint size={19} />, show: can(me, 'audit.view') },
    ] },
    { label: 'Administration', items: [
      { to: '/admin/org', label: 'Organization', icon: <IconBuildingCommunity size={19} />, show: can(me, 'admin.org') },
      { to: '/admin/users', label: 'Users & access', icon: <IconUsers size={19} />, show: can(me, 'admin.users') },
      { to: '/admin/roles', label: 'Roles & permissions', icon: <IconShieldLock size={19} />, show: can(me, 'admin.users') },
      { to: '/admin/projects', label: 'Projects & breakdown', icon: <IconAffiliate size={19} />, show: can(me, 'project.manage') },
      { to: '/admin/document-types', label: 'Document types', icon: <IconFileDescription size={19} />, show: can(me, 'admin.config') },
    ] },
  ]
  const active = (to: string) => (to === '/' ? loc.pathname === '/' : loc.pathname.startsWith(to))
  const logout = async () => { try { await api.post('/auth/logout') } finally { qc.clear(); nav('/login') } }
  const width = collapsed ? 76 : 248

  return (
    <MAppShell layout="alt" header={{ height: 60 }} navbar={{ width, breakpoint: 'sm', collapsed: { mobile: !mobileOpen } }} padding={0}>
      <MAppShell.Navbar withBorder={false}>
        <div className="nav">
          <div className="brand" onClick={() => nav('/')} style={{ cursor: 'pointer' }}>
            <div className="brand-logo"><svg width="18" height="18" viewBox="0 0 64 64"><path d="M32 6 L37 27 L58 34 L37 39 L34 58 L29 58 L30 39 L8 36 L8 30 L30 27 Z" fill="#fff" /></svg></div>
            {!collapsed && <div><div className="brand-name">ADA · ELM</div><div className="brand-sub">Engineering Lifecycle</div></div>}
          </div>
          <ScrollArea style={{ flex: 1 }}>
            {groups.map((g) => {
              const items = g.items.filter((i) => i.show !== false)
              if (!items.length) return null
              return (
                <div key={g.label}>
                  {!collapsed ? <div className="sider-section">{g.label}</div> : <div style={{ height: 14 }} />}
                  {items.map((i) => (
                    <Tooltip key={i.to} label={i.label} position="right" disabled={!collapsed}>
                      <div className={`nav-link ${active(i.to) ? 'active' : ''}`} onClick={() => { nav(i.to); mobile.close() }} style={collapsed ? { justifyContent: 'center' } : undefined}>
                        {collapsed && i.badge ? <Indicator size={8} color="red">{i.icon}</Indicator> : i.icon}
                        {!collapsed && <span style={{ flex: 1 }}>{i.label}</span>}
                        {!collapsed && !!i.badge && <Badge size="sm" variant="filled" circle={i.badge < 10}>{i.badge}</Badge>}
                      </div>
                    </Tooltip>
                  ))}
                </div>
              )
            })}
          </ScrollArea>
          {!collapsed && <Text size="xs" c="rgba(226,232,240,.4)" p="md">Intranet build · all actions audited</Text>}
        </div>
      </MAppShell.Navbar>
      <MAppShell.Header className="app-header">
        {/* left: menu toggles */}
        <Group gap={6} wrap="nowrap" className="hdr-left">
          <Burger opened={mobileOpen} onClick={mobile.toggle} hiddenFrom="sm" size="sm" />
          <Burger opened={!collapsed} onClick={() => setCollapsed(!collapsed)} visibleFrom="sm" size="sm" />
        </Group>
        {/* centre: global search */}
        <UnstyledButton className="search-trigger" onClick={openPalette}>
          <IconSearch size={16} /> <span style={{ flex: 1 }}>Search documents, LRUs, people…</span> <Kbd size="xs">Ctrl K</Kbd>
        </UnstyledButton>
        {/* right: environment, theme, notifications, profile */}
        <Group gap={6} wrap="nowrap" justify="flex-end" className="hdr-right">
        {me?.settings.environment !== 'prod' && <Badge color="grape" variant="light">{me?.settings.environment?.toUpperCase()}</Badge>}
        <Tooltip label={colorScheme === 'dark' ? 'Light mode' : 'Dark mode'}>
          <ActionIcon variant="subtle" color="gray" size="lg" radius="xl" onClick={toggleColorScheme}>{colorScheme === 'dark' ? <IconSun size={19} /> : <IconMoon size={19} />}</ActionIcon>
        </Tooltip>
        <Indicator label={notifs.data?.unread || 0} size={16} disabled={!notifs.data?.unread} color="red" offset={6}>
          <ActionIcon variant="subtle" color="gray" size="lg" radius="xl" onClick={bell.open}><IconBell size={19} /></ActionIcon>
        </Indicator>
        <Menu position="bottom-end" width={290} shadow="lg">
          <Menu.Target><UnstyledButton><UserAvatar user={me?.user} size={34} /></UnstyledButton></Menu.Target>
          <Menu.Dropdown>
            <div style={{ padding: '8px 12px' }}>
              <Text fw={600}>{me?.user.full_name}</Text>
              <Text size="xs" c="dimmed">{me?.user.designation} · {me?.orgs.map((o) => o.code).join(', ')}</Text>
              <Group gap={4} mt={6}>{me?.roles.map((r) => <Badge key={r} size="xs" variant="outline" color="gray">{r}</Badge>)}</Group>
            </div>
            <Menu.Divider />
            <Menu.Item leftSection={<IconUserCog size={16} />} onClick={() => nav('/inbox?tab=delegation')}>Delegations</Menu.Item>
            <Menu.Item leftSection={<IconChecklist size={16} />} onClick={() => nav('/tasks')}>My tasks</Menu.Item>
            <Menu.Divider />
            <Menu.Item color="red" leftSection={<IconLogout size={16} />} onClick={logout}>Sign out</Menu.Item>
          </Menu.Dropdown>
        </Menu>
        </Group>
      </MAppShell.Header>
      <MAppShell.Main>
        <ErrorBoundary key={loc.pathname}>
          <Outlet />
        </ErrorBoundary>
      </MAppShell.Main>
      <CommandPalette />
      <NotificationDrawer opened={bellOpen} onClose={bell.close} />
    </MAppShell>
  )
}

function NotificationDrawer({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const { data, refetch } = useNotifications()
  const nav = useNavigate()
  const [filter, setFilter] = useState('unread')
  const items = (data?.items || []).filter((n: any) => filter === 'all' || !n.read)
  const color: Record<string, string> = { error: '#dc2626', warning: '#d97706', success: '#16a34a', info: '#2563eb' }
  return (
    <Drawer opened={opened} onClose={onClose} position="right" size={420} title={<Text fw={650}>Notifications</Text>}>
      <Group mb="sm" justify="space-between">
        <SegmentedControl size="xs" value={filter} onChange={setFilter} data={[{ label: `Unread (${data?.unread || 0})`, value: 'unread' }, { label: 'All', value: 'all' }]} />
        <Button size="xs" variant="subtle" onClick={async () => { await api.post('/notifications/read', []); refetch() }}>Mark all read</Button>
      </Group>
      <Stack gap={2}>
        {!items.length && <Text c="dimmed" ta="center" py="xl">You are all caught up 🎉</Text>}
        {items.map((n: any) => (
          <UnstyledButton key={n.id} className="inbox-item" style={{ opacity: n.read ? 0.65 : 1 }}
            onClick={async () => { await api.post('/notifications/read', [n.id]); refetch(); if (n.link) { nav(n.link); onClose() } }}>
            <Group align="flex-start" wrap="nowrap" gap={10}>
              <span style={{ width: 8, height: 8, borderRadius: 4, marginTop: 7, flex: 'none', background: color[n.severity] || '#2563eb' }} />
              <div>
                <Text size="sm" fw={n.read ? 400 : 600}>{n.title}</Text>
                <Text size="xs">{n.body}</Text>
                <Text size="xs" c="dimmed" mt={2}><When at={n.created_at} /></Text>
              </div>
            </Group>
          </UnstyledButton>
        ))}
      </Stack>
    </Drawer>
  )
}


