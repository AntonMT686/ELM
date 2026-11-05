import { Button, Stack, Text, Title } from '@mantine/core'
import { useNavigate } from 'react-router-dom'

export default function NotFound({ title = 'Page not found', text = 'The page you are looking for does not exist or you no longer have access.' }: { title?: string; text?: string }) {
  const nav = useNavigate()
  return (
    <Stack align="center" justify="center" h="60vh" gap="xs">
      <Title order={1} fz={64} c="dimmed">404</Title>
      <Title order={3}>{title}</Title>
      <Text c="dimmed">{text}</Text>
      <Button mt="md" onClick={() => nav('/')}>Back to home</Button>
    </Stack>
  )
}

export function Notice({ title, text, action }: { title: string; text?: string; action?: React.ReactNode }) {
  return (
    <Stack align="center" justify="center" py={50} gap={6}>
      <Title order={4}>{title}</Title>
      {text && <Text c="dimmed" size="sm" ta="center" maw={460}>{text}</Text>}
      {action}
    </Stack>
  )
}
