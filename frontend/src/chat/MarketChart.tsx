import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { ChartBlock } from '../api/client'

export default function MarketChart({ block }: { block: ChartBlock }) {
  const rows = new Map<string, Record<string, string | number>>()
  block.series.forEach((series, index) => series.points.forEach(point => {
    const row = rows.get(point.date) || { date: point.date }
    row['s' + index] = point.close
    rows.set(point.date, row)
  }))
  const data = [...rows.values()].sort((a, b) => String(a.date).localeCompare(String(b.date)))
  const colors = ['#6366f1', '#10b981', '#f59e0b']
  return <figure className="my-4 w-full min-w-0 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm" aria-label={block.title}>
    <figcaption className="mb-3 text-sm font-semibold text-slate-800">{block.title}</figcaption>
    <p className="mb-3 text-xs text-slate-500">{block.comparison === 'base_100' ? 'Base 100 · primera fecha común' : 'Precio · ' + block.series[0]?.currency}</p>
    <div className="h-64 w-full min-w-0" role="img" aria-label={'Gráfico de líneas: ' + block.series.map(s => s.symbol).join(', ')}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ left: 0, right: 12, top: 8, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="date" minTickGap={40} tick={{ fontSize: 10 }} />
          <YAxis width={65} domain={['auto', 'auto']} tick={{ fontSize: 10 }} tickFormatter={value => Number(value).toLocaleString('es-AR', { maximumFractionDigits: 2 })} />
          <Tooltip /><Legend wrapperStyle={{ fontSize: 12 }} />
          {block.series.map((series, index) => <Line key={index} type="linear" dataKey={'s' + index} name={series.symbol + ' · ' + (series.currency || 'moneda no informada')} stroke={colors[index]} dot={false} connectNulls={false} isAnimationActive={false} />)}
        </LineChart>
      </ResponsiveContainer>
    </div>
    <div className="mt-3 space-y-1 text-[10px] leading-relaxed text-slate-500">
      {block.series.map((series, index) => <p key={index}>{series.symbol} · {series.market} · {series.source} · {series.currency || 'Moneda no informada'} · {series.start} — {series.end} · Precios sin ajustar · Liquidación: {series.settlement} · Último dato: {series.as_of || 'no informado'}</p>)}
      <p>Evolución de precios; no incluye cupones/dividendos ni conversión de moneda.</p>
    </div>
  </figure>
}
