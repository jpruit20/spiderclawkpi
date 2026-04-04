import { LineChart, Line, ResponsiveContainer, CartesianGrid, XAxis, YAxis, Tooltip, Legend } from 'recharts'
import { KPIDaily } from '../lib/types'

type TrendLine = {
  key: 'revenue' | 'orders' | 'sessions' | 'tickets_created' | 'tickets_resolved' | 'open_backlog' | 'first_response_time' | 'resolution_time'
  label: string
  color: string
  axisId?: 'left' | 'right'
}

export function TrendChart({ rows, lines, height = 320 }: { rows: KPIDaily[]; lines?: TrendLine[]; height?: number }) {
  if (!rows.length) {
    return <div className="state-message">No chart data returned.</div>
  }

  const resolvedLines = lines?.length ? lines : [
    { key: 'revenue', label: 'Revenue', color: '#6ea8ff', axisId: 'left' as const },
    { key: 'orders', label: 'Orders', color: '#39d08f', axisId: 'left' as const },
    { key: 'sessions', label: 'Sessions', color: '#ffb257', axisId: 'right' as const },
  ]
  const hasRightAxis = resolvedLines.some((line) => line.axisId === 'right')

  return (
    <div className="chart-wrap">
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={rows}>
          <CartesianGrid stroke="rgba(255,255,255,0.08)" />
          <XAxis dataKey="business_date" stroke="#9fb0d4" />
          <YAxis yAxisId="left" stroke="#9fb0d4" />
          {hasRightAxis ? <YAxis yAxisId="right" orientation="right" stroke="#9fb0d4" /> : null}
          <Tooltip />
          <Legend />
          {resolvedLines.map((line) => (
            <Line key={line.key} type="monotone" name={line.label} dataKey={line.key} yAxisId={line.axisId || 'left'} stroke={line.color} strokeWidth={2} dot={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
