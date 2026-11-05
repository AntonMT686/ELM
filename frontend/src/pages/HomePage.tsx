import { AreaChart, BarChart } from '@mantine/charts'
import { Badge, Button, Card, Group, Progress, RingProgress, SegmentedControl, SimpleGrid, Skeleton, Stack, Text, Timeline, Title } from '@mantine/core'
import { IconArrowRight, IconCircleCheck, IconClockHour4, IconEdit, IconFileCertificate, IconInbox, IconPlus, IconRefresh, IconRosetteDiscountCheck } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useInbox, useMe } from '../api/hooks'
import { EmptyBlock, Kpi, StatusTag, TypeBadge, UserAvatar, When } from '../components/common'
import { MiniStages } from '../components/LifecycleTracker'

const label = (s: string) => s.replace('_', ' ').toLowerCase().replace(/^\w/, (c) => c.toUpperCase())

export default function HomePage() {
  const { data: me } = useMe()
  const nav = useNavigate()
  const [project, setProject] = useState('all')
  const { data, isLoading } = useQuery({ queryKey: ['dashboard', project], queryFn: () => api.get('/dashboard', { project_id: project === 'all' ? undefined : project }) })
  const inbox = useInbox()
  const hour = new Date().getHours()
  const greet = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'
  const k = data?.kpis

  return (
    <div className="page">
      <div className="hero" style={{ marginBottom: 18 }}>
        <Group justify="space-between" align="center" wrap="wrap" style={{ position: 'relative', zIndex: 1 }}>
          <div>
            <Text size="sm" opacity={0.85}>{dayjs().format('dddd, DD MMMM YYYY')}</Text>
            <h2>{greet}, {me?.user.full_name.split(' ').slice(-2).join(' ')}</h2>
            <Text opacity={0.88} mt={4}>
              {k ? (k.my_pending ? <>You have <b>{k.my_pending}</b> item{k.my_pending > 1 ? 's' : ''} waiting for your action{k.my_overdue ? <> — <b>{k.my_overdue} overdue</b></> : null}.</> : 'Your action inbox is clear.') : ' '}
              {me?.perspective === 'OVERSIGHT' && ' Programme oversight view is enabled.'}
            </Text>
          </div>
          <Group>
            <Button size="md" variant="white" color="dark" leftSection={<IconInbox size={18} />} onClick={() => nav('/inbox')} styles={{ root: { background: 'rgba(255,255,255,.16)', color: '#fff' } }}>Open inbox</Button>
            <Button size="md" variant="white" leftSection={<IconPlus size={18} />} onClick={() => nav('/documents?new=1')}>New document</Button>
          </Group>
        </Group>
      </div>

      {me && me.projects.length > 1 && (
        <SegmentedControl mb="md" value={project} onChange={setProject} data={[{ label: 'All programmes', value: 'all' }, ...me.projects.map((p) => ({ label: p.code, value: p.id }))]} />
      )}

      <SimpleGrid cols={{ base: 2, md: 3, xl: 6 }} spacing="md">
        <Kpi label="Awaiting my action" value={k?.my_pending} icon={<IconInbox size={20} />} color="brand" hint={k?.my_overdue ? `${k.my_overdue} overdue` : 'on track'} onClick={() => nav('/inbox')} />
        <Kpi label="My drafts / rework" value={k?.my_drafts} icon={<IconEdit size={20} />} color="violet" onClick={() => nav('/documents?mine=1')} />
        <Kpi label="In review (scope)" value={k?.in_review} icon={<IconRefresh size={20} />} color="cyan" onClick={() => nav('/documents?status=IN_REVIEW')} />
        <Kpi label="Approved, to release" value={k?.awaiting_release} icon={<IconCircleCheck size={20} />} color="orange" onClick={() => nav('/documents?status=APPROVED')} />
        <Kpi label="Released · 30 days" value={k?.released_30d} icon={<IconFileCertificate size={20} />} color="teal" onClick={() => nav('/releases')} />
        <Kpi label="My open tasks" value={k?.my_open_tasks} icon={<IconClockHour4 size={20} />} color="pink" onClick={() => nav('/tasks')} />
      </SimpleGrid>

      <SimpleGrid cols={{ base: 1, xl: 3 }} spacing="md" mt="md">
        <Card>
          <Group justify="space-between" mb="sm"><Title order={5}>Your next actions</Title><Button variant="subtle" size="xs" rightSection={<IconArrowRight size={14} />} onClick={() => nav('/inbox')}>View all</Button></Group>
          {inbox.isLoading ? <Skeleton h={220} /> : !(inbox.data?.pending || []).length ? <EmptyBlock text="Nothing waiting on you" /> : (
            <Stack gap={2}>
              {(inbox.data?.pending || []).slice(0, 6).map((t) => (
                <div key={t.id} className="inbox-item" onClick={() => nav(`/inbox?task=${t.id}`)}>
                  <Group wrap="nowrap" gap={10}>
                    <UserAvatar user={t.initiator} size={32} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <Group gap={6} wrap="nowrap"><TypeBadge type={t.document.type} /><Text size="sm" fw={600}>{t.document.number}</Text>{t.overdue && <Badge color="red" size="xs">Overdue</Badge>}</Group>
                      <Text size="xs" c="dimmed" truncate>{t.document.title}</Text>
                      <Group gap={8} mt={4}><Badge size="xs" color={t.stage.type === 'signature' ? 'yellow' : 'blue'}>{t.stage.name}</Badge><MiniStages stages={t.stages} index={t.stage.index} /></Group>
                    </div>
                    {t.due_at && <Text size="xs" c="dimmed" ta="right">due<br /><When at={t.due_at} /></Text>}
                  </Group>
                </div>
              ))}
            </Stack>
          )}
        </Card>
        <Card>
          <Title order={5} mb="sm">Document pipeline</Title>
          {isLoading ? <Skeleton h={240} /> : (
            <BarChart h={250} data={(data?.pipeline || []).map((p: any) => ({ status: label(p.status), Documents: p.count }))} dataKey="status" orientation="vertical" yAxisProps={{ width: 120 }}
              series={[{ name: 'Documents', color: 'brand.5' }]} gridAxis="none" withXAxis={false} barProps={{ radius: 6 }} />
          )}
        </Card>
        <Card>
          <Group justify="space-between" mb="sm"><Title order={5}>Review aging</Title><Text size="xs" c="dimmed">pending reviews</Text></Group>
          {isLoading ? <Skeleton h={240} /> : (
            <BarChart h={250} data={(data?.aging || []).map((a: any) => ({ bucket: a.bucket, Pending: a.count }))} dataKey="bucket" series={[{ name: 'Pending', color: 'orange.5' }]} barProps={{ radius: 6 }} tickLine="none" />
          )}
        </Card>
      </SimpleGrid>

      <SimpleGrid cols={{ base: 1, xl: 2 }} spacing="md" mt="md">
        <Card>
          <Group justify="space-between" mb="md"><Title order={5}>Programme progress</Title><Text size="xs" c="dimmed">weighted by document lifecycle state</Text></Group>
          <SimpleGrid cols={{ base: 1, md: 2 }}>
            {(data?.projects || []).map((p: any) => (
              <div key={p.id} className="kpi" onClick={() => nav(`/explorer/${p.id}`)} style={{ display: 'flex', gap: 14, alignItems: 'center' }}>
                <RingProgress size={84} thickness={8} roundCaps sections={[{ value: p.progress, color: 'teal' }]} label={<Text ta="center" fw={700} size="sm">{p.progress}%</Text>} />
                <div>
                  <Text fw={650} size="lg">{p.code}</Text>
                  <Text size="xs" c="dimmed">{p.name}</Text>
                  <Group gap={4} mt={6}><Badge size="xs" color="gray">{p.total} docs</Badge><Badge size="xs" color="teal">{p.released} released</Badge><Badge size="xs">{p.in_review} in review</Badge></Group>
                </div>
              </div>
            ))}
          </SimpleGrid>
          {!!data?.directorates?.length && <Title order={6} mt="lg" mb="xs">Directorate contribution</Title>}
          {(data?.directorates || []).map((d: any) => (
            <Group key={d.id} wrap="nowrap" py={5}>
              <Text size="sm" w={230} truncate><b>{d.code}</b> <Text span size="xs" c="dimmed">{d.name}</Text></Text>
              <Progress value={d.progress} style={{ flex: 1 }} radius="xl" />
              <Text size="xs" c="dimmed" w={70} ta="right">{d.progress}% · {d.total}</Text>
            </Group>
          ))}
        </Card>
        <Stack gap="md">
          <Card>
            <Group justify="space-between" mb="sm"><Title order={5}>Release throughput</Title><Text size="xs" c="dimmed">last 12 weeks</Text></Group>
            <AreaChart h={170} data={(data?.throughput || []).map((t: any) => ({ week: t.week, Released: t.released }))} dataKey="week" series={[{ name: 'Released', color: 'teal.6' }]} curveType="monotone" withDots={false} gridAxis="y" />
          </Card>
          <Card>
            <Title order={5} mb="sm">Recent activity</Title>
            <Timeline bulletSize={12} lineWidth={2}>
              {(data?.activity || []).slice(0, 7).map((a: any, i: number) => (
                <Timeline.Item key={i} color={a.action.includes('release') ? 'teal' : a.action.includes('request_changes') || a.action.includes('reject') ? 'red' : a.action.includes('sign') ? 'yellow' : 'blue'}>
                  <Text size="sm" className="clickable" onClick={() => nav(`/documents/${a.document_id}`)}>{a.summary}</Text>
                  <Text size="xs" c="dimmed">{a.actor?.full_name || 'System'} · <When at={a.at} /></Text>
                </Timeline.Item>
              ))}
            </Timeline>
          </Card>
        </Stack>
      </SimpleGrid>

      {!!data?.recent_releases?.length && (
        <Card mt="md">
          <Group justify="space-between" mb="sm"><Title order={5}>Latest releases</Title><Button variant="subtle" size="xs" rightSection={<IconArrowRight size={14} />} onClick={() => nav('/releases')}>Release register</Button></Group>
          <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }}>
            {data.recent_releases.map((r: any) => (
              <div key={r.release_no} className="kpi" style={{ padding: 14 }} onClick={() => nav(`/documents/${r.document.id}`)}>
                <Group gap={6}><IconRosetteDiscountCheck size={18} color="#16a34a" /><Text fw={650}>{r.release_no}</Text><StatusTag status="RELEASED" /></Group>
                <Text fw={550} mt={6} size="sm">{r.document.number}</Text>
                <Text size="xs" c="dimmed" truncate>{r.document.title}</Text>
                <Text size="xs" c="dimmed" mt={4}><When at={r.released_at} /></Text>
              </div>
            ))}
          </SimpleGrid>
        </Card>
      )}
    </div>
  )
}
