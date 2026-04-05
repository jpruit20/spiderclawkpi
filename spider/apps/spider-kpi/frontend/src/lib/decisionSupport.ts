export type ThresholdTone = 'good' | 'warn' | 'bad' | 'muted'

export function toneForConversion(value?: number | null): ThresholdTone {
  if (value == null) return 'muted'
  if (value >= 1.5) return 'good'
  if (value >= 1.0) return 'warn'
  return 'bad'
}

export function toneForMer(value?: number | null): ThresholdTone {
  if (value == null) return 'muted'
  if (value >= 4) return 'good'
  if (value >= 3) return 'warn'
  return 'bad'
}

export function toneForAov(value?: number | null): ThresholdTone {
  if (value == null) return 'muted'
  if (value >= 500) return 'good'
  if (value >= 400) return 'warn'
  return 'bad'
}

export function toneForBacklog(value?: number | null): ThresholdTone {
  if (value == null) return 'muted'
  if (value <= 150) return 'good'
  if (value <= 250) return 'warn'
  return 'bad'
}

export function toneForTicketsPer100Orders(value?: number | null): ThresholdTone {
  if (value == null) return 'muted'
  if (value <= 10) return 'good'
  if (value <= 20) return 'warn'
  return 'bad'
}
