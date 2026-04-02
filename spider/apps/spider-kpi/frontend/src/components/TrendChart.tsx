import { LineChart, Line, ResponsiveContainer, CartesianGrid, XAxis, YAxis, Tooltip, Legend } from 'recharts'
import { KPIDaily } from '../lib/types'

export function TrendChart({ rows }: { rows: KPIDaily[] }) {
  if (!rows.length) {
    return <div className="state-message">No chart data returned.</div>
  }

  return (
    <div className="chart-wrap">
      <ResponsiveContainer width="100%" height={320}>
        <LineChart data={rows}>
          <CartesianGrid stroke="rgba(255,255,255,0.08)" />
          <XAxis dataKey="business_date" stroke="#9fb0d4" />
          <YAxis stroke="#9fb0d4" />
          <Tooltip />
          <Legend />
          <Line type="monotone" dataKey="revenue" stroke="#6ea8ff" strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey="orders" stroke="#39d08f" strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey="sessions" stroke="#ffb257" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
