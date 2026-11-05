import { Alert, Button, Code, Stack, Text } from '@mantine/core'
import { IconAlertTriangle } from '@tabler/icons-react'
import { Component, type ReactNode } from 'react'

/** Catches render errors in a page so the user sees a message instead of a blank screen. */
export default class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }
  static getDerivedStateFromError(error: Error) {
    return { error }
  }
  componentDidCatch(error: Error) {
    console.error('Page crashed:', error)
  }
  render() {
    if (!this.state.error) return this.props.children
    return (
      <Stack p="xl" maw={720} mx="auto" mt="xl">
        <Alert color="red" icon={<IconAlertTriangle />} title="This page could not be displayed">
          <Text size="sm">Something went wrong while showing this page. Your data is safe. Try reloading; if it keeps happening, send this message to the ELM support team.</Text>
          <Code block mt="sm">{this.state.error.message}</Code>
        </Alert>
        <Button variant="default" onClick={() => location.reload()} w={160}>Reload page</Button>
      </Stack>
    )
  }
}
