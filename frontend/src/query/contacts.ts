import { useMemo } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { adaptContact } from '../api/adapters'
import {
  createContact,
  deleteContact,
  listContacts,
  listContactUtterances,
} from '../api/contacts'
import type { ApiContact, ApiUtterance } from '../types/api'
import type { Contact } from '../types/domain'
import { queryKeys } from './keys'

function mapContact(apiContact: ApiContact): Contact {
  return adaptContact(apiContact)
}

export function upsertContactInCache(
  existing: Contact[] | undefined,
  apiContact: ApiContact,
): Contact[] {
  const nextContact = mapContact(apiContact)
  if (!existing) return [nextContact]

  const index = existing.findIndex((contact) => contact.id === nextContact.id)
  if (index === -1) return [...existing, nextContact]

  const next = [...existing]
  next[index] = nextContact
  return next
}

export function useContactsListQuery() {
  return useQuery({
    queryKey: queryKeys.contacts.list(),
    queryFn: listContacts,
    select: (contacts) => contacts.map(mapContact),
  })
}

export function useContactUtterancesQuery(contactId: string | null, enabled = true) {
  return useQuery<ApiUtterance[]>({
    queryKey: contactId
      ? queryKeys.contacts.utterances(contactId)
      : [...queryKeys.contacts.utterancesRoot(), 'disabled'] as const,
    queryFn: () => listContactUtterances(contactId as string),
    enabled: enabled && !!contactId,
  })
}

export function useContactsData() {
  const contactsQuery = useContactsListQuery()
  const contacts = contactsQuery.data ?? []

  const contactsById = useMemo(
    () => new Map(contacts.map((contact) => [contact.id, contact])),
    [contacts],
  )

  const contactById = (id: string | null | undefined): Contact | null => {
    if (!id) return null
    return contactsById.get(id) ?? null
  }

  return {
    ...contactsQuery,
    contacts,
    contactsById,
    contactById,
  }
}

export function useCreateContactMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ name, notes = '' }: { name: string; notes?: string }) =>
      createContact(name, notes),
    onSuccess: (apiContact) => {
      queryClient.setQueryData<Contact[]>(
        queryKeys.contacts.list(),
        (existing) => upsertContactInCache(existing, apiContact),
      )
    },
  })
}

export function useDeleteContactMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (contactId: string) => deleteContact(contactId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.contacts.list() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.queue.list() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.sessions.list() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.contacts.utterancesRoot() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.sessions.utterancesRoot() }),
      ])
    },
  })
}
