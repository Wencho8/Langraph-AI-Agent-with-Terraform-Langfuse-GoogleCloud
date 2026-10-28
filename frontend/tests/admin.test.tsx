import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { api, type Session } from '../src/api/client'
import AuthForm from '../src/auth/AuthForm'
import AdminUsers from '../src/admin/AdminUsers'

vi.mock('../src/api/client', async original => ({ ...await original<typeof import('../src/api/client')>(), api: vi.fn() }))
const mockedApi = vi.mocked(api)
beforeEach(() => vi.resetAllMocks())

it('pending registration stays at access form and never enters the chat', async () => {
  mockedApi.mockResolvedValue({ status: 'pending_approval', message: 'Un administrador debe aprobar tu cuenta.' })
  const onLogin = vi.fn()
  render(<AuthForm onLogin={onLogin} />)
  fireEvent.click(screen.getByRole('button', { name: 'Creá una cuenta' }))
  fireEvent.change(screen.getByLabelText('Nombre'), { target: { value: 'Pending' } })
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'pending' } })
  for (const name of ['Contraseña', 'Repetí la contraseña']) fireEvent.change(screen.getByLabelText(name), { target: { value: 'a sufficiently long password' } })
  fireEvent.submit(screen.getByRole('button', { name: 'Crear mi cuenta' }).closest('form')!)
  expect(await screen.findByRole('alert')).toHaveTextContent('Un administrador')
  expect(onLogin).not.toHaveBeenCalled()
  expect(screen.getByRole('button', { name: 'Iniciar sesión' })).toBeInTheDocument()
})

it('admin approval posts only the blocked field with CSRF', async () => {
  const session: Session = { user: { id: 'admin', display_name: 'Admin', username: 'admin', is_admin: true }, csrf_token: 'csrf', expires_at: '' }
  mockedApi.mockResolvedValue([{ id: 'pending-id', display_name: 'Pending', username: 'pending', blocked: true, is_admin: false }])
  render(<AdminUsers session={session} onExpired={vi.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Aprobar' }))
  await waitFor(() => expect(mockedApi).toHaveBeenCalledWith('/auth/admin/users/pending-id/access', { method: 'POST', csrf: 'csrf', body: { blocked: false } }))
})
