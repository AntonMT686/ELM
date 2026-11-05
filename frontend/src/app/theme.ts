import { createTheme, type MantineColorsTuple } from '@mantine/core'

const brand: MantineColorsTuple = ['#eef4ff', '#dbe6ff', '#b4caff', '#8aacfd', '#6791fb', '#5080fa', '#2563eb', '#1d4fd1', '#1745bb', '#0b3aa6']

export const theme = createTheme({
  primaryColor: 'brand',
  colors: { brand },
  primaryShade: { light: 6, dark: 5 },
  fontFamily: "'Inter Variable', 'Segoe UI', system-ui, -apple-system, sans-serif",
  headings: { fontFamily: "'Inter Variable', 'Segoe UI', system-ui, sans-serif", fontWeight: '650' },
  defaultRadius: 'md',
  cursorType: 'pointer',
  components: {
    Card: { defaultProps: { withBorder: true, radius: 'lg', padding: 'lg' } },
    Paper: { defaultProps: { radius: 'lg' } },
    Button: { defaultProps: { radius: 'md' } },
    Badge: { defaultProps: { radius: 'sm', variant: 'light' } },
    Modal: { defaultProps: { radius: 'lg', centered: true, overlayProps: { blur: 3, backgroundOpacity: 0.35 } } },
    Drawer: { defaultProps: { overlayProps: { blur: 2, backgroundOpacity: 0.3 } } },
    Tooltip: { defaultProps: { withArrow: true, openDelay: 250 } },
    Table: { defaultProps: { highlightOnHover: true, verticalSpacing: 'sm' } },
  },
})
