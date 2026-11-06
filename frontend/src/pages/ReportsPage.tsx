import { Button, Card, Group, Select, SimpleGrid, Text, ThemeIcon } from '@mantine/core'
import { IconBug, IconFileDescription, IconFileSpreadsheet, IconFileTypePdf, IconFlask, IconGitPullRequest, IconHierarchy3, IconListCheck, IconReportAnalytics, IconRocket, IconSchema } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { useProjects } from '../api/hooks'
import { PageTitle } from '../components/common'

const META: Record<string, { icon: JSX.Element; color: string; what: string }> = {
  documents: { icon: <IconFileDescription size={20} />, color: 'violet', what: 'Every controlled document with type, level, revision, status and review cycles.' },
  requirements: { icon: <IconListCheck size={20} />, color: 'blue', what: 'Coverage figures and the full requirement traceability matrix.' },
  design: { icon: <IconSchema size={20} />, color: 'indigo', what: 'Design records with version, baseline, satisfied requirements and code links.' },
  development: { icon: <IconGitPullRequest size={20} />, color: 'cyan', what: 'Development tasks with requirements, branches, merge requests and commits.' },
  testing: { icon: <IconFlask size={20} />, color: 'teal', what: 'Test summary: runs, pass rates, exit criteria and test cases with last results.' },
  defects: { icon: <IconBug size={20} />, color: 'red', what: 'Defects by severity and status, with builds and age.' },
  deployment: { icon: <IconRocket size={20} />, color: 'orange', what: 'What runs where, and every deployment with its attempts and test evidence.' },
  traceability: { icon: <IconHierarchy3 size={20} />, color: 'grape', what: 'Requirement → document → design → development → code → test → defect → deployment, with gaps.' },
}

export default function ReportsPage() {
  const projects = useProjects()
  const kinds = useQuery<any[]>({ queryKey: ['report-kinds'], queryFn: () => api.get('/report-kinds'), staleTime: 3600_000 })
  const [project, setProject] = useState<string | null>(null)
  useEffect(() => { if (!project && projects.data?.length) setProject(projects.data[0].id) }, [projects.data, project])
  return (
    <div className="page">
      <PageTitle icon={<IconReportAnalytics size={22} />} title="Reports" sub="Phase reports for a project, as PDF for records and CSV for analysis. They contain only what you are allowed to see, and generating one is audited."
        extra={<Select w={260} value={project} onChange={setProject} allowDeselect={false} data={(projects.data || []).map((p) => ({ value: p.id, label: `${p.code} — ${p.name}` }))} />} />
      <SimpleGrid cols={{ base: 1, md: 2, xl: 4 }}>
        {(kinds.data || []).map((k) => {
          const m = META[k.kind]
          return (
            <Card key={k.kind} withBorder>
              <Group gap="sm" wrap="nowrap" align="flex-start">
                <ThemeIcon size={36} radius="md" variant="light" color={m?.color}>{m?.icon}</ThemeIcon>
                <div><Text fw={650}>{k.title}</Text><Text size="xs" c="dimmed">{m?.what}</Text></div>
              </Group>
              <Group mt="md" gap="xs">
                <Button size="xs" leftSection={<IconFileTypePdf size={14} />} component="a" href={`/api/v1/projects/${project}/reports/${k.kind}.pdf`} disabled={!project}>PDF</Button>
                <Button size="xs" variant="default" leftSection={<IconFileSpreadsheet size={14} />} component="a" href={`/api/v1/projects/${project}/reports/${k.kind}.csv`} disabled={!project}>CSV</Button>
              </Group>
            </Card>
          )
        })}
      </SimpleGrid>
    </div>
  )
}
