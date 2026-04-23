/**
 * Charcoal usage model — first-principles caloric estimator for the JIT
 * auto-ship program.
 *
 * The grill telemetry stream records when a grill was cooking and at what
 * temperature, but it does not know *which* fuel was loaded — lump hardwood
 * or briquette. Since those two fuels have very different energy densities
 * (and shipping density), we model each cook session as an *amount of
 * thermal energy delivered*, then convert that energy into pounds of fuel
 * given an assumed (or customer-declared) fuel type.
 *
 * All constants here are seed values drawn from the published literature
 * and Weber-kettle field burn-rate tests. They are intentionally exposed as
 * tunable parameters so the prediction engine can be recalibrated as real
 * usage data comes in — the whole point of the JIT program's first phase
 * is to collect ground-truth fuel reloads and close the loop on these
 * numbers.
 */

export type FuelType = 'lump' | 'briquette' | 'unknown'

/* ------------------------------------------------------------------ */
/*  Fuel energy density — BTU per pound                               */
/* ------------------------------------------------------------------ */
// Hardwood lump is denser-carbon. Briquettes have binders + fillers that
// reduce net combustible mass per pound. These are seed values — override
// via ModelParams as we learn.
export const FUEL_BTU_PER_LB = {
  lump: 9_000, // hardwood lump charcoal
  briquette: 6_500, // standard briquette
} as const

/* ------------------------------------------------------------------ */
/*  Grill thermal throughput curve (BTU / hour at steady state)       */
/* ------------------------------------------------------------------ */
// How much useful heat the grill is putting out *into the cook*, at a given
// target temperature. Real fuel burn is higher because of combustion losses
// (see `combustionEfficiency`). These numbers are calibrated against a
// 22" Weber kettle with partially closed vents.
export interface ThermalBand {
  label: string
  minF: number
  maxF: number
  btuPerHour: number
}

export const THERMAL_BANDS: ThermalBand[] = [
  { label: 'Idle / warming', minF: 0, maxF: 200, btuPerHour: 8_000 },
  { label: 'Low & slow', minF: 200, maxF: 275, btuPerHour: 12_000 },
  { label: 'Medium', minF: 275, maxF: 400, btuPerHour: 18_000 },
  { label: 'Hot & fast', minF: 400, maxF: 1_200, btuPerHour: 25_000 },
]

export function thermalBandForTemp(tempF: number | null | undefined): ThermalBand {
  const t = tempF ?? 0
  for (const band of THERMAL_BANDS) {
    if (t >= band.minF && t < band.maxF) return band
  }
  return THERMAL_BANDS[THERMAL_BANDS.length - 1]
}

/* ------------------------------------------------------------------ */
/*  Tunable model parameters                                          */
/* ------------------------------------------------------------------ */
export interface ModelParams {
  /** 0–1. Fraction of fuel BTU that ends up as useful grill heat.
   *  Defaults to 0.60 — real-world kettle steady-state efficiency is
   *  commonly cited in the 0.5–0.7 band. */
  combustionEfficiency: number
  /** BTU/lb for lump hardwood. Override to recalibrate against a
   *  specific supplier's product (e.g. Jealous Devil vs generic). */
  lumpBtuPerLb: number
  /** BTU/lb for briquette. Override per-brand. */
  briquetteBtuPerLb: number
  /** Override the thermal throughput curve. Rarely needed — most
   *  tuning should live in combustionEfficiency. */
  thermalBands?: ThermalBand[]
}

export const DEFAULT_PARAMS: ModelParams = {
  combustionEfficiency: 0.6,
  lumpBtuPerLb: FUEL_BTU_PER_LB.lump,
  briquetteBtuPerLb: FUEL_BTU_PER_LB.briquette,
}

/* ------------------------------------------------------------------ */
/*  Per-session inputs & outputs                                      */
/* ------------------------------------------------------------------ */
export interface CookSessionInput {
  session_start: string | null
  session_end: string | null
  session_duration_seconds: number | null
  /** Preferred — the actual cook temp achieved. */
  avg_cook_temp: number | null
  /** Fallback — the target when we don't have an actual reading. */
  target_temp: number | null
}

export interface SessionFuelEstimate {
  durationHours: number
  tempF: number
  band: ThermalBand
  btuDelivered: number
  btuFuelRequired: number
  lumpLb: number
  briquetteLb: number
}

export function estimateSession(
  session: CookSessionInput,
  params: ModelParams = DEFAULT_PARAMS,
): SessionFuelEstimate {
  const durationHours = Math.max(0, (session.session_duration_seconds ?? 0) / 3600)
  const tempF = session.avg_cook_temp ?? session.target_temp ?? 0
  const band = thermalBandForTemp(tempF)
  const btuDelivered = durationHours * band.btuPerHour
  const eff = Math.max(0.05, Math.min(1, params.combustionEfficiency))
  const btuFuelRequired = btuDelivered / eff
  const lumpLb = btuFuelRequired / params.lumpBtuPerLb
  const briquetteLb = btuFuelRequired / params.briquetteBtuPerLb
  return { durationHours, tempF, band, btuDelivered, btuFuelRequired, lumpLb, briquetteLb }
}

/* ------------------------------------------------------------------ */
/*  Device-level rollups                                              */
/* ------------------------------------------------------------------ */
export interface DeviceUsageRollup {
  sessionCount: number
  totalHours: number
  totalBtuDelivered: number
  totalLumpLb: number
  totalBriquetteLb: number
  /** Sessions grouped by YYYY-MM-DD of session_start (ET). */
  daily: DailyUsageRow[]
  /** Time buckets (Low & slow, Medium, etc.). */
  byBand: BandUsageRow[]
}

export interface DailyUsageRow {
  date: string
  sessions: number
  hours: number
  lumpLb: number
  briquetteLb: number
}

export interface BandUsageRow {
  band: string
  sessions: number
  hours: number
  lumpLb: number
  briquetteLb: number
}

export function rollupDevice(
  sessions: CookSessionInput[],
  params: ModelParams = DEFAULT_PARAMS,
): DeviceUsageRollup {
  const daily: Record<string, DailyUsageRow> = {}
  const bands: Record<string, BandUsageRow> = {}
  let totalHours = 0
  let totalBtu = 0
  let totalLump = 0
  let totalBriquette = 0

  for (const s of sessions) {
    const est = estimateSession(s, params)
    if (est.durationHours <= 0) continue
    totalHours += est.durationHours
    totalBtu += est.btuDelivered
    totalLump += est.lumpLb
    totalBriquette += est.briquetteLb

    // Group by date-in-ET. session_start is already an ISO timestamp.
    const day = (s.session_start || '').slice(0, 10) || 'unknown'
    if (!daily[day]) daily[day] = { date: day, sessions: 0, hours: 0, lumpLb: 0, briquetteLb: 0 }
    daily[day].sessions += 1
    daily[day].hours += est.durationHours
    daily[day].lumpLb += est.lumpLb
    daily[day].briquetteLb += est.briquetteLb

    const b = est.band.label
    if (!bands[b]) bands[b] = { band: b, sessions: 0, hours: 0, lumpLb: 0, briquetteLb: 0 }
    bands[b].sessions += 1
    bands[b].hours += est.durationHours
    bands[b].lumpLb += est.lumpLb
    bands[b].briquetteLb += est.briquetteLb
  }

  return {
    sessionCount: sessions.filter((s) => (s.session_duration_seconds ?? 0) > 0).length,
    totalHours,
    totalBtuDelivered: totalBtu,
    totalLumpLb: totalLump,
    totalBriquetteLb: totalBriquette,
    daily: Object.values(daily).sort((a, b) => a.date.localeCompare(b.date)),
    byBand: Object.values(bands).sort((a, b) => b.lumpLb - a.lumpLb),
  }
}

/* ------------------------------------------------------------------ */
/*  Fleet-level rollup from telemetry_history_daily                   */
/* ------------------------------------------------------------------ */
// telemetry_history_daily doesn't give us per-session granularity — it
// gives us per-day fleet totals. We approximate fleet charcoal use by
// (sessions × mean session duration × thermal throughput at avg cook temp).
//
// Cohort filters slice the daily counts *before* the rollup, using the
// JSONB distribution fields the API already returns.
export interface FleetDailyInput {
  business_date: string
  total_events: number
  active_devices: number
  engaged_devices: number
  avg_cook_temp: number | null
  /** sessions (or events proxy). */
  sessions: number
  /** Distribution maps. Pass empty {} if unavailable. */
  model_distribution: Record<string, number>
  firmware_distribution: Record<string, number>
  cook_styles: Record<string, number>
}

export interface FleetRollupFilters {
  /** If set, restrict to sessions in these grill models. Empty = no filter. */
  models?: string[]
  /** If set, restrict to these firmware versions. */
  firmwareVersions?: string[]
  /** If set, restrict to these cook styles. */
  cookStyles?: string[]
}

export interface FleetDailyRow {
  date: string
  sessions: number
  engagedDevices: number
  avgCookTemp: number | null
  hours: number
  lumpLb: number
  briquetteLb: number
}

export interface FleetRollup {
  days: number
  totalSessions: number
  totalHours: number
  totalLumpLb: number
  totalBriquetteLb: number
  perDeviceAvgLumpLb: number
  perDeviceAvgBriquetteLb: number
  daily: FleetDailyRow[]
}

function filteredShare(
  dist: Record<string, number>,
  allowed?: string[],
): number {
  if (!allowed || allowed.length === 0) return 1
  const total = Object.values(dist).reduce((a, b) => a + b, 0)
  if (total <= 0) return 0
  const kept = allowed.reduce((s, key) => s + (dist[key] || 0), 0)
  return Math.max(0, Math.min(1, kept / total))
}

export function rollupFleet(
  rows: FleetDailyInput[],
  /** Average cook duration (seconds) across the fleet in the window. */
  avgSessionDurationSeconds: number,
  filters: FleetRollupFilters = {},
  params: ModelParams = DEFAULT_PARAMS,
): FleetRollup {
  const daily: FleetDailyRow[] = []
  let totalSessions = 0
  let totalHours = 0
  let totalLump = 0
  let totalBriquette = 0
  let engagedDeviceSum = 0
  const avgSessionHours = Math.max(0, avgSessionDurationSeconds / 3600)

  for (const row of rows) {
    // Compose the cohort share across three independent cuts. Each cut is
    // a share of sessions/events that match the filter; we multiply them
    // as independent probabilities (rough but conservative — the true joint
    // distribution isn't in the daily rollup, so we don't pretend to know
    // it better than that).
    const modelShare = filteredShare(row.model_distribution, filters.models)
    const fwShare = filteredShare(row.firmware_distribution, filters.firmwareVersions)
    const styleShare = filteredShare(row.cook_styles, filters.cookStyles)
    const share = modelShare * fwShare * styleShare

    const sessions = Math.max(0, row.sessions * share)
    const engaged = Math.max(0, row.engaged_devices * share)
    const hours = sessions * avgSessionHours
    const band = thermalBandForTemp(row.avg_cook_temp)
    const btu = hours * band.btuPerHour
    const eff = Math.max(0.05, Math.min(1, params.combustionEfficiency))
    const btuFuel = btu / eff
    const lumpLb = btuFuel / params.lumpBtuPerLb
    const briquetteLb = btuFuel / params.briquetteBtuPerLb

    totalSessions += sessions
    totalHours += hours
    totalLump += lumpLb
    totalBriquette += briquetteLb
    engagedDeviceSum += engaged

    daily.push({
      date: row.business_date,
      sessions,
      engagedDevices: engaged,
      avgCookTemp: row.avg_cook_temp,
      hours,
      lumpLb,
      briquetteLb,
    })
  }

  const avgEngaged = daily.length > 0 ? engagedDeviceSum / daily.length : 0
  return {
    days: daily.length,
    totalSessions,
    totalHours,
    totalLumpLb: totalLump,
    totalBriquetteLb: totalBriquette,
    perDeviceAvgLumpLb: avgEngaged > 0 ? totalLump / avgEngaged : 0,
    perDeviceAvgBriquetteLb: avgEngaged > 0 ? totalBriquette / avgEngaged : 0,
    daily,
  }
}

/* ------------------------------------------------------------------ */
/*  JIT (Just-In-Time) reorder forecast                               */
/* ------------------------------------------------------------------ */
export interface JitInputs {
  /** Fuel the customer has picked for auto-ship. */
  fuel: 'lump' | 'briquette'
  /** Bag size in pounds (default 15 lb briquette bag / 20 lb lump bag). */
  bagSizeLb: number
  /** Customer's currently-declared on-hand inventory (pounds). */
  onHandLb: number
  /** Shipping lead time (days). Order must land before they run out. */
  leadTimeDays: number
  /** Safety buffer (days of cook). Ship earlier than zero-runout. */
  bufferDays: number
}

export interface JitForecast {
  fuel: 'lump' | 'briquette'
  /** Trailing-window burn rate, lb / day. */
  burnRateLbPerDay: number
  /** Days of fuel remaining at current burn rate. */
  daysOfRunway: number
  /** Date (ISO yyyy-mm-dd) when we should place the ship trigger. */
  nextShipDate: string | null
  /** How many bags we expect to need over a 90-day horizon. */
  bags90d: number
  /** Pounds expected to consume over a 90-day horizon. */
  lb90d: number
  /** Burn rate confidence based on trailing sample size. */
  confidence: 'low' | 'medium' | 'high'
}

export const DEFAULT_JIT: JitInputs = {
  fuel: 'briquette',
  bagSizeLb: 15,
  onHandLb: 0,
  leadTimeDays: 5,
  bufferDays: 3,
}

export function forecastJit(
  rollup: DeviceUsageRollup,
  inputs: JitInputs = DEFAULT_JIT,
): JitForecast {
  const daily = rollup.daily
  const days = daily.length || 1
  const totalLb = inputs.fuel === 'lump' ? rollup.totalLumpLb : rollup.totalBriquetteLb
  const burnRateLbPerDay = totalLb / Math.max(1, days)

  // Confidence rises with (days of data) × (sessions observed).
  const conf: 'low' | 'medium' | 'high' =
    daily.length >= 30 && rollup.sessionCount >= 10
      ? 'high'
      : daily.length >= 14 && rollup.sessionCount >= 4
        ? 'medium'
        : 'low'

  const daysOfRunway = burnRateLbPerDay > 0 ? inputs.onHandLb / burnRateLbPerDay : Infinity
  const today = new Date()
  let nextShipDate: string | null = null
  if (Number.isFinite(daysOfRunway)) {
    const shipOffsetDays = Math.max(0, daysOfRunway - inputs.leadTimeDays - inputs.bufferDays)
    const d = new Date(today.getTime() + shipOffsetDays * 86400_000)
    nextShipDate = d.toISOString().slice(0, 10)
  }

  const lb90d = burnRateLbPerDay * 90
  const bags90d = inputs.bagSizeLb > 0 ? lb90d / inputs.bagSizeLb : 0

  return {
    fuel: inputs.fuel,
    burnRateLbPerDay,
    daysOfRunway,
    nextShipDate,
    bags90d,
    lb90d,
    confidence: conf,
  }
}

/* ------------------------------------------------------------------ */
/*  Fuel-equivalent conversions                                       */
/* ------------------------------------------------------------------ */
/** How many pounds of briquette produce the same BTU as `lumpLb`? */
export function lumpToBriquette(lumpLb: number, params: ModelParams = DEFAULT_PARAMS): number {
  return (lumpLb * params.lumpBtuPerLb) / params.briquetteBtuPerLb
}

/** Reverse. */
export function briquetteToLump(briquetteLb: number, params: ModelParams = DEFAULT_PARAMS): number {
  return (briquetteLb * params.briquetteBtuPerLb) / params.lumpBtuPerLb
}
