import { useId } from 'react'
import type { ToolStep } from '../api/stream'
import Icon from '../Icon'

const labels: Record<string, string> = {
  search_instruments: 'Buscar instrumentos', get_quote: 'Consultar cotización',
  get_price_history: 'Consultar histórico', show_chart: 'Preparar gráfico',
}
function ThinkingDots() {
  return <span role="status" aria-label="El asistente sigue trabajando" className="inline-flex items-center gap-1 px-1">
    {[0, 1, 2].map(index => <span key={index} aria-hidden="true" className="size-1 rounded-full bg-indigo-400 animate-bounce motion-reduce:animate-none" style={{ animationDelay: `${index * 150}ms` }} />)}
  </span>
}

export default function ToolActivity({ steps, expanded, onToggle, active = false }: { steps: ToolStep[]; active?: boolean; expanded: boolean; onToggle: () => void }) {
  const panelId = useId()
  if (!steps.length) return null
  return <section className="mb-4 mt-3 overflow-hidden rounded-xl border border-slate-200/80 bg-slate-50/70 text-xs text-slate-600" aria-label="Actividad de herramientas">
    <button type="button" className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition hover:bg-slate-100/80 focus-visible:outline-2 focus-visible:outline-indigo-500" onClick={onToggle} aria-expanded={expanded} aria-controls={panelId}>
      <span className="flex items-center gap-2"><Icon name="spark" className="size-3.5 text-indigo-400" /><span className="font-medium">Herramientas</span><span className="rounded-md bg-white px-1.5 py-0.5 text-[10px] text-slate-400 ring-1 ring-slate-200/80">{steps.length}</span></span>
      <Icon name="chevron" className={'size-3 transition-transform ' + (expanded ? 'rotate-90' : '')} />
    </button>
    {expanded && <div id={panelId} className="border-t border-slate-200/70 px-4 py-3.5">
      <ol className="space-y-3" aria-live="polite" aria-relevant="additions text">
      {steps.map((step, index) => <li key={step.id} className="flex items-start gap-3">
        <span className="mt-0.5 grid size-5 shrink-0 place-items-center" aria-hidden="true"><span className={'size-2.5 rounded-full border transition-colors duration-300 ' + (step.status === 'running' ? 'border-slate-300 bg-white' : 'border-blue-500 bg-blue-500')} /></span>
        <div className="min-w-0 flex-1"><p className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1"><span className="text-[11px] font-medium text-slate-600">{labels[step.name] || 'Ejecutar herramienta'} <span className="ml-1 text-[10px] font-normal text-slate-400">#{index + 1}</span></span></p></div>
      </li>)}
      </ol>
      {active && <div className="ml-8 mt-3 flex h-4 items-center"><ThinkingDots /></div>}
    </div>}
  </section>
}
