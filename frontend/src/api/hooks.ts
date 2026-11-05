import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { notifications } from '@mantine/notifications'
import { api, errorText } from './client'
import type { DocFull, DocType, InboxTask, Me, Project, WorkflowRun } from './types'

export const useMe = () => useQuery<Me>({ queryKey: ['me'], queryFn: () => api.get('/auth/me'), staleTime: 60_000, retry: false })
export const useDocTypes = () => useQuery<DocType[]>({ queryKey: ['doc-types'], queryFn: () => api.get('/document-types'), staleTime: 300_000 })
export const useDomains = () => useQuery<any[]>({ queryKey: ['domains'], queryFn: () => api.get('/process-domains'), staleTime: 300_000 })
export const useOrgUnits = () => useQuery<any[]>({ queryKey: ['org-units'], queryFn: () => api.get('/org-units'), staleTime: 120_000 })
export const useProjects = () => useQuery<Project[]>({ queryKey: ['projects'], queryFn: () => api.get('/projects'), staleTime: 60_000 })
export const useUsers = (q?: string) => useQuery<any[]>({ queryKey: ['users', q || ''], queryFn: () => api.get('/users', { q }), staleTime: 60_000 })
export const useRoles = () => useQuery<any[]>({ queryKey: ['roles'], queryFn: () => api.get('/roles'), staleTime: 60_000 })
export const useDoc = (id?: string) => useQuery<DocFull>({ queryKey: ['doc', id], queryFn: () => api.get(`/documents/${id}`), enabled: !!id })
export const useDocWorkflow = (id?: string) => useQuery<WorkflowRun[]>({ queryKey: ['doc-wf', id], queryFn: () => api.get(`/documents/${id}/workflow`), enabled: !!id })
export const useInbox = () =>
  useQuery<{ pending: InboxTask[]; completed: InboxTask[]; submitted: any[] }>({ queryKey: ['inbox'], queryFn: () => api.get('/inbox'), refetchInterval: 60_000 })
export const useNotifications = () => useQuery<any>({ queryKey: ['notifications'], queryFn: () => api.get('/notifications'), refetchInterval: 45_000 })

/** Mutation with toast + cache invalidation, so every action gives immediate, friendly feedback. */
export function useAction<TVars = any, TRes = any>(fn: (v: TVars) => Promise<TRes>, opts: { success?: string | ((r: TRes) => string); invalidate?: any[][]; onDone?: (r: TRes) => void } = {}) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: (r) => {
      if (opts.success) notifications.show({ color: 'teal', title: 'Done', message: typeof opts.success === 'function' ? opts.success(r) : opts.success })
      ;(opts.invalidate || []).forEach((k) => qc.invalidateQueries({ queryKey: k }))
      qc.invalidateQueries({ queryKey: ['me'] })
      opts.onDone?.(r)
    },
    onError: (e) => notifications.show({ color: 'red', title: 'Could not complete', message: errorText(e), autoClose: 7000 }),
  })
}

export const can = (me: Me | undefined, perm: string) => !!me?.permissions.includes(perm)
