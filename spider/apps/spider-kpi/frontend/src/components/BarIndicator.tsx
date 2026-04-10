export function BarIndicator({ value, max, color }: { value: number; max: number; color: string }) {
  const pct = Math.min(100, Math.max(0, (value / (max || 1)) * 100))
  return (
    <div className="venom-bar-track">
      <div className="venom-bar-fill" style={{ width: `${pct}%`, background: color }} />
    </div>
  )
}
