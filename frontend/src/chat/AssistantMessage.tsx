import { lazy, Suspense } from 'react'
import type { MessageBlock } from '../api/client'
import MarkdownMessage from './MarkdownMessage'
const MarketChart = lazy(() => import('./MarketChart'))

export default function AssistantMessage({ content, blocks }: { content: string; blocks?: MessageBlock[] }) {
  if (!blocks?.length) return <MarkdownMessage content={content} />
  return <>{blocks.map((block, index) => block.type === 'text'
    ? <MarkdownMessage key={index} content={block.text} />
    : <Suspense key={block.id} fallback={<p className="py-4 text-xs text-slate-400">Preparando gráfico…</p>}><MarketChart block={block} /></Suspense>)}</>
}
