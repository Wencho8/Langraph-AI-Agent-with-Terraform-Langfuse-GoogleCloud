import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import MarkdownMessage from '../src/chat/MarkdownMessage'

it('renders bold text, paragraphs, lists, links and tables as semantic elements', () => {
  render(<MarkdownMessage content={'Las **obligaciones negociables (ON)** son deuda.\n\nAntes de invertir:\n\n- **Moneda:** dólares\n- **Riesgo:** incumplimiento\n\n[Fuente](https://example.com)\n\n| Tasa | Plazo |\n| --- | --- |\n| 8 % | 3 años |'} />)
  expect(screen.getByText('obligaciones negociables (ON)').tagName).toBe('STRONG')
  expect(screen.getByRole('list')).toBeInTheDocument()
  expect(screen.getAllByRole('listitem')).toHaveLength(2)
  expect(screen.getByRole('link', { name: 'Fuente' })).toHaveAttribute('rel', 'noopener noreferrer')
  expect(screen.getByRole('table')).toBeInTheDocument()
  expect(screen.queryByText(/\*\*/)).not.toBeInTheDocument()
})

it('does not execute raw HTML, load images or allow executable links', () => {
  const { container } = render(<MarkdownMessage content={'<script>alert("bad")</script>\n\n<img src="https://tracker.test/pixel" onerror="alert(1)">\n\n![tracking](https://tracker.test/pixel)\n\n[unsafe](javascript:alert%281%29)\n\n**Safe content**'} />)
  expect(container.querySelector('script, img, iframe')).toBeNull()
  expect(screen.queryByRole('link', { name: 'unsafe' })).not.toBeInTheDocument()
  expect(screen.getByText('Safe content')).toBeInTheDocument()
})
