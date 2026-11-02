import { useState } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import ToolActivity from '../src/chat/ToolActivity'
import { finishPending, type ToolStep } from '../src/api/stream'

function Panel({ steps, active = false }: { steps: ToolStep[]; active?: boolean }) {
  const [expanded, setExpanded] = useState(true)
  return <ToolActivity active={active} steps={steps} expanded={expanded} onToggle={() => setExpanded(value => !value)} />
}

describe('live tool activity', () => {
  it('starts expanded, supports repeated tools, updates results, and stays collapsed when a call finishes', () => {
    const steps: ToolStep[] = [
      { id: 'quote-1', name: 'get_quote', status: 'completed', duration_ms: 1200 },
      { id: 'quote-2', name: 'get_quote', status: 'running' },
    ]
    const view = render(<Panel steps={steps} active />)
    const toggle = screen.getByRole('button', { name: /Herramientas/ })
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
    expect(screen.getAllByText('Consultar cotización', { exact: false })).toHaveLength(2)
    expect(screen.getByRole('status', { name: 'El asistente sigue trabajando' })).toBeInTheDocument()
    expect(screen.queryByText(/Completada|En curso|Falló|Interrumpida/)).not.toBeInTheDocument()
    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('list')).not.toBeInTheDocument()
    view.rerender(<Panel steps={[steps[0], { ...steps[1], status: 'failed', duration_ms: 500 }]} />)
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(toggle)
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
    expect(screen.queryByText(/Completada|Falló/)).not.toBeInTheDocument()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('closes pending indicators on interruption without changing finished calls', () => {
    const steps: ToolStep[] = [
      { id: 'one', name: 'search_instruments', status: 'completed' },
      { id: 'two', name: 'get_price_history', status: 'running' },
    ]
    const finished = finishPending(steps)
    expect(steps[1].status).toBe('running')
    expect(finished.map(step => step.status)).toEqual(['completed', 'cancelled'])
    render(<Panel steps={finished} />)
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
    expect(screen.queryByText(/Interrumpida|Falló/)).not.toBeInTheDocument()
  })

  it('keeps thinking below the steps between batches and hides it when finished or collapsed', () => {
    const steps: ToolStep[] = [{ id: 'one', name: 'get_quote', status: 'completed' }]
    const view = render(<ToolActivity steps={steps} active expanded onToggle={() => {}} />)
    expect(screen.getByRole('status', { name: 'El asistente sigue trabajando' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Herramientas/ })).not.toContainElement(screen.getByRole('status'))
    view.rerender(<ToolActivity steps={steps} active={false} expanded onToggle={() => {}} />)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    view.rerender(<ToolActivity steps={steps} active expanded={false} onToggle={() => {}} />)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(screen.queryByRole('list')).not.toBeInTheDocument()
  })

  it('renders nothing when the model uses no tools', () => {
    render(<Panel steps={[]} />)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})
