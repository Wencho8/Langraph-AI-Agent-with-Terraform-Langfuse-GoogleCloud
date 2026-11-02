import { render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import AssistantMessage from '../src/chat/AssistantMessage'
import { appendText, type ChartBlock, type MessageBlock } from '../src/api/client'
import { readEvents, type ChatEvent } from '../src/api/stream'

vi.mock('recharts', () => ({ ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  LineChart: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Line: () => null, XAxis: () => null, YAxis: () => null, Tooltip: () => null, Legend: () => null, CartesianGrid: () => null }))
const chart: ChartBlock = { type: 'chart', id: 'chart-one', title: 'AL30 histórico', comparison: 'absolute', note: 'Prices only',
  series: [{ instrument_id: 'bCBA:AL30:t1', symbol: 'AL30', market: 'bCBA', currency: 'ARS', source: 'IOL', start: '2026-01-01', end: '2026-02-01', adjustment: 'unadjusted', settlement: 'provider_default', as_of: '2026-02-01', points: [{ date: '2026-01-02', close: 100 }] }] }

it('renders saved Markdown/chart/Markdown blocks in order, with source and currency', async () => {
  const { container } = render(<AssistantMessage content="fallback" blocks={[{ type: 'text', text: '**Antes**' }, chart, { type: 'text', text: 'Después' }]} />)
  expect(screen.getByText('Antes').tagName).toBe('STRONG')
  expect(await screen.findByText('AL30 histórico')).toBeInTheDocument()
  expect(screen.getByText(/IOL · ARS/)).toBeInTheDocument()
  expect(container.textContent!.indexOf('Antes')).toBeLessThan(container.textContent!.indexOf('AL30 histórico'))
  expect(container.textContent!.indexOf('AL30 histórico')).toBeLessThan(container.textContent!.indexOf('Después'))
  expect(screen.queryByText('fallback')).not.toBeInTheDocument()
})

it('keeps old message Markdown and appends new prose after a chart without mutating previous state', () => {
  render(<AssistantMessage content="**Historial anterior**" />)
  expect(screen.getByText('Historial anterior')).toBeInTheDocument()
  const previous: MessageBlock[] = [{ type: 'text', text: 'Antes' }, chart]
  const next = appendText(previous, 'Después')
  expect(previous).toHaveLength(2)
  expect(next.map(block => block.type)).toEqual(['text', 'chart', 'text'])
})

it('accepts a chart SSE event between text chunks and the canonical completed blocks', async () => {
  const frames = [
    ['started', { turn_id: 'turn' }], ['delta', { text: 'Antes' }], ['chart', { block: chart }],
    ['delta', { text: 'Después' }], ['completed', { text: 'AntesDespués', blocks: [{ type: 'text', text: 'Antes' }, chart, { type: 'text', text: 'Después' }] }],
  ].map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join('')
  const events: ChatEvent[] = []
  await readEvents(new ReadableStream({ start(controller) { controller.enqueue(new TextEncoder().encode(frames)); controller.close() } }), event => events.push(event))
  expect(events.map(event => event.event)).toEqual(['started', 'delta', 'chart', 'delta', 'completed'])
})
