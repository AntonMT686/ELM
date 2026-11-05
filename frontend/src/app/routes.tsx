import { Center, Loader } from '@mantine/core'
import NotFound from '../components/NotFound'
import { lazy, Suspense, useEffect } from 'react'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { setUnauthorizedHandler } from '../api/client'
import { useMe } from '../api/hooks'
import AppShell from '../layouts/AppShell'
import LoginPage from '../pages/LoginPage'

const Home = lazy(() => import('../pages/HomePage'))
const Inbox = lazy(() => import('../pages/InboxPage'))
const Explorer = lazy(() => import('../pages/ExplorerPage'))
const Documents = lazy(() => import('../pages/DocumentsPage'))
const DocumentPage = lazy(() => import('../pages/DocumentPage'))
const EditorPage = lazy(() => import('../pages/EditorPage'))
const Releases = lazy(() => import('../pages/ReleasesPage'))
const Tasks = lazy(() => import('../pages/TasksPage'))
const Planning = lazy(() => import('../pages/PlanningPage'))
const Requirements = lazy(() => import('../pages/RequirementsPage'))
const AdminTaskLifecycle = lazy(() => import('../pages/admin/TaskLifecyclePage'))
const Workflows = lazy(() => import('../pages/WorkflowsPage'))
const WorkflowDesigner = lazy(() => import('../pages/WorkflowDesignerPage'))
const Audit = lazy(() => import('../pages/AuditPage'))
const AdminOrg = lazy(() => import('../pages/admin/OrgPage'))
const AdminUsers = lazy(() => import('../pages/admin/UsersPage'))
const AdminRoles = lazy(() => import('../pages/admin/RolesPage'))
const AdminDocTypes = lazy(() => import('../pages/admin/DocTypesPage'))
const AdminProjects = lazy(() => import('../pages/admin/ProjectsPage'))

const Loading = () => (
  <Center h="60vh">
    <Loader type="dots" size="lg" />
  </Center>
)

function Protected({ children }: { children: JSX.Element }) {
  const { data, isLoading, isError, isFetching } = useMe()
  const loc = useLocation()
  if (isLoading || (isError && isFetching)) return <Loading />
  if (isError || !data) return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname + loc.search)}`} replace />
  return children
}

export default function AppRoutes() {
  const nav = useNavigate()
  // NOTE: braces matter — the effect must not *return* the handler, or React would call it as the
  // cleanup on every navigation and bounce the user to /login in an endless loop.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      if (!location.pathname.startsWith('/login')) nav('/login')
    })
  }, [nav])
  return (
    <Suspense fallback={<Loading />}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/documents/:id/edit" element={<Protected><EditorPage /></Protected>} />
        <Route element={<Protected><AppShell /></Protected>}>
          <Route index element={<Home />} />
          <Route path="inbox" element={<Inbox />} />
          <Route path="explorer" element={<Explorer />} />
          <Route path="explorer/:projectId" element={<Explorer />} />
          <Route path="documents" element={<Documents />} />
          <Route path="documents/:id" element={<DocumentPage />} />
          <Route path="releases" element={<Releases />} />
          <Route path="tasks" element={<Tasks />} />
          <Route path="planning" element={<Planning />} />
          <Route path="requirements" element={<Requirements />} />
          <Route path="requirements/:projectId" element={<Requirements />} />
          <Route path="planning/:projectId" element={<Planning />} />
          <Route path="workflows" element={<Workflows />} />
          <Route path="workflows/:id" element={<WorkflowDesigner />} />
          <Route path="audit" element={<Audit />} />
          <Route path="admin/task-lifecycle" element={<AdminTaskLifecycle />} />
          <Route path="admin/org" element={<AdminOrg />} />
          <Route path="admin/users" element={<AdminUsers />} />
          <Route path="admin/roles" element={<AdminRoles />} />
          <Route path="admin/document-types" element={<AdminDocTypes />} />
          <Route path="admin/projects" element={<AdminProjects />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </Suspense>
  )
}
