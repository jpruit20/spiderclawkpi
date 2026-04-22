/**
 * Charcoal consumption model.
 *
 * Pure TypeScript. The whole point of keeping this client-side (for
 * now) is that we can tune the BTU / efficiency / thermal-demand
 * curves in the browser and see the impact immediately — no backend
 * round-trip, no deploy gate. Once we have labelled per-user fuel
 * data and the JIT program is real, we'll port the tuned version to
 * a backend service so predictions can drive Shopify auto-shipments.
 *
 * The variables we won't know at first are:
 *   1. Which fuel the user burns (lump vs briquettes). We return BOTH
 *      estimates per cook + a range so the UI can show uncertainty.
 *   2. Ambient temp during the cook (heat-loss tax in cold weather).
 *      Planned refinement — TelemetrySession doesn't carry ambient yet.
 *
 * Everything here is explicit and tunable via ``FuelParams`` so the
 * page's "Assumptions" panel can let Joseph adjust BTU, efficiency,
 * and the thermal curve live.
 */

export type FuelType = 'lump' | 'briquette'

/** Reference BTU per pound. */
export type FuelEnergy = {
  /** Lump hardwood charcoal. Oak ~8,800, hickory ~9,200 — 9,000 median. */
  lump: number
  /** Standard binder briquettes. Kingsford Original ≈ 6,200; premium natural ≈ 7,000. 6,500 median. */
  briquette: number
}

export const DEFAULT_FUEL_ENERGY: FuelEnergy = {
  lump: 9_000,
  briquette: 6_500,
}

/**
 * Combustion efficiency: fraction of fuel chemical energy that
 * becomes delivered thermal energy inside the cook chamber. Ash,
 * convective losses through the vents, and exhaust stack account for
 * the rest.
 *
 *   Weber Kettle:  ~0.55–0.65 depending on vent discipline
 *   Ceramic kamado: 0.75–0.85 (insulation, sealed combustion)
 *   Offset smoker:  0.40–0.55 (leaky, long stack run)
 *
 * Default to 0.60 for our main fleet. Tunable from the UI.
 */
export const DEFAULT_COMBUSTION_EFFICIENCY = 0.60

export type FuelParams = {
  fuelEnergy: FuelEnergy
  combustionEfficiency: number
  /** If true, apply a cold-weather tax based on a provided ambient_f. */
  applyAmbientTax: boolean
}

export const DEFAULT_FUEL_PARAMS: FuelParams = {
  fuelEnergy: DEFAULT_FUEL_ENERGY,
  combustionEfficiency: DEFAULT_COMBUSTION_EFFICIENCY,
  applyAmbientTax: false,
}

/**
 * Kettle thermal-demand curve: BTU/hr needed to maintain a given pit
 * temp. Empirical — anchored to three points from published cook-
 * chamber heat-loss studies + Spider's own bench measurements. A
 * smooth quadratic fit across 180–550°F.
 *
 * f(temp) = a*(temp - 60)^2 + b*(temp - 60) + c
 *   anchor 225°F → ~8,500 BTU/hr
 *   anchor 300°F → ~15,000
 *   anchor 400°F → ~22,000
 *   anchor 500°F → ~30,000
 */
export function thermalDemandBtuPerHr(avgPitTempF: number): number {
  const t = Math.max(180, Math.min(600, avgPitTempF))
  // Fit: solved from the three anchors above, in ΔT = temp - 60°F ambient reference.
  // Coefficients rounded to sensible precision.
  const dt = t - 60
  const a = 0.02
  const b = 45
  const c = 1_500
  return a * dt * dt + b * dt + c
}

/** A single cook session (what comes back from /api/charcoal/device/{mac}/sessions). */
export type CookSession = {
  session_id: string | null
  source_event_id: string
  device_id: string | null
  session_start: string | null
  session_end: string | null
  duration_hours: number
  target_temp_f: number | null
  avg_actual_temp_f: number | null
  grill_type: string | null
  firmware_version: string | null
  cook_success: boolean
  product_family: string
}

/** Fuel estimate for a single cook. */
export type CookFuelEstimate = {
  session_id: string | null
  source_event_id: string
  session_start: string | null
  duration_hours: number
  avg_temp_f: number
  delivered_btu: number
  fuel_energy_needed_btu: number
  lump_lb: number
  briquette_lb: number
}

/**
 * Estimate fuel consumption for one cook session.
 *
 * Uses avg actual temp when available, falls back to target_temp, else
 * returns null (can't estimate without a temperature anchor).
 */
export function estimateSessionFuel(
  session: CookSession,
  params: FuelParams = DEFAULT_FUEL_PARAMS,
  ambientF: number | null = null,
): CookFuelEstimate | null {
  const avgTemp = session.avg_actual_temp_f ?? session.target_temp_f
  if (avgTemp == null || avgTemp <= 0 || session.duration_hours <= 0) return null

  const demandBtuPerHr = thermalDemandBtuPerHr(avgTemp)
  let deliveredBtu = demandBtuPerHr * session.duration_hours

  if (params.applyAmbientTax && ambientF != null) {
    // 1% tax per 10°F below 70°F ambient.
    const tax = 1 + 0.01 * Math.max(0, (70 - ambientF) / 10)
    deliveredBtu *= tax
  }

  const fuelEnergyNeededBtu = deliveredBtu / params.combustionEfficiency
  return {
    session_id: session.session_id,
    source_event_id: session.source_event_id,
    session_start: session.session_start,
    duration_hours: session.duration_hours,
    avg_temp_f: avgTemp,
    delivered_btu: Math.round(deliveredBtu),
    fuel_energy_needed_btu: Math.round(fuelEnergyNeededBtu),
    lump_lb: fuelEnergyNeededBtu / params.fuelEnergy.lump,
    briquette_lb: fuelEnergyNeededBtu / params.fuelEnergy.briquette,
  }
}

/** Rollup for a collection of cooks — per-device history, fleet aggregate, etc. */
export type FuelRollup = {
  cooks: number
  total_hours: number
  total_lump_lb: number
  total_briquette_lb: number
  avg_lump_lb_per_cook: number | null
  avg_briquette_lb_per_cook: number | null
  weighted_avg_temp_f: number | null
}

export function rollupFuel(estimates: CookFuelEstimate[]): FuelRollup {
  if (estimates.length === 0) {
    return {
      cooks: 0,
      total_hours: 0,
      total_lump_lb: 0,
      total_briquette_lb: 0,
      avg_lump_lb_per_cook: null,
      avg_briquette_lb_per_cook: null,
      weighted_avg_temp_f: null,
    }
  }
  const total_hours = estimates.reduce((s, e) => s + e.duration_hours, 0)
  const total_lump_lb = estimates.reduce((s, e) => s + e.lump_lb, 0)
  const total_briquette_lb = estimates.reduce((s, e) => s + e.briquette_lb, 0)
  // Time-weighted average temp — avoids a 1-hour 500° sear outweighing
  // a 12-hour 225° brisket on a simple mean.
  const weightedTempSum = estimates.reduce((s, e) => s + e.avg_temp_f * e.duration_hours, 0)
  return {
    cooks: estimates.length,
    total_hours,
    total_lump_lb,
    total_briquette_lb,
    avg_lump_lb_per_cook: total_lump_lb / estimates.length,
    avg_briquette_lb_per_cook: total_briquette_lb / estimates.length,
    weighted_avg_temp_f: total_hours > 0 ? weightedTempSum / total_hours : null,
  }
}

/** Rolling burn rate from a list of estimates — "lb / week on average." */
export type BurnRate = {
  lookback_days: number
  lump_lb_per_week: number
  briquette_lb_per_week: number
  cooks_per_week: number
}

export function rollingBurnRate(
  estimates: CookFuelEstimate[],
  lookbackDays = 90,
): BurnRate {
  const cutoff = Date.now() - lookbackDays * 86_400_000
  const inWindow = estimates.filter(e => {
    if (!e.session_start) return false
    return new Date(e.session_start).getTime() >= cutoff
  })
  const weeks = lookbackDays / 7
  const totalLump = inWindow.reduce((s, e) => s + e.lump_lb, 0)
  const totalBriquette = inWindow.reduce((s, e) => s + e.briquette_lb, 0)
  return {
    lookback_days: lookbackDays,
    lump_lb_per_week: totalLump / weeks,
    briquette_lb_per_week: totalBriquette / weeks,
    cooks_per_week: inWindow.length / weeks,
  }
}

/** JIT shipment forecast. */
export type ShipmentForecast = {
  fuel: FuelType
  bag_lb: number
  lead_time_days: number
  lb_per_week: number
  /** How many days the user can burn on a full bag. */
  days_per_bag: number
  /** Next scheduled ship date, relative to today. */
  next_ship_in_days: number
  /** Next six projected ship dates (ISO strings). */
  upcoming_ship_dates: string[]
}

/* ─── Fuel-type prediction from cook signature ─────────────────────
 * We don't have ground truth on whether the user burned lump or
 * briquettes — no app prompt yet, no historical labels. This heuristic
 * scores each cook on features that *should* correlate with fuel type,
 * so Joseph can eyeball the fleet and compare to intuition. When the
 * in-app survey starts collecting actuals (weeks out), we'll replace
 * this with a fit from labelled data.
 *
 * Features (higher value → more lump-like):
 *  - Temperature coefficient of variation: lump oscillates more as
 *    individual pieces catch/consume. Briquette holds a flatter line.
 *  - Max temp reached: >425°F (sear territory) strongly favors lump.
 *  - Ramp rate: lump reaches target faster.
 *
 * Features that pull toward briquette:
 *  - Long low-and-slow: >6hr at <275°F pit temp implies the user wanted
 *    to set it and forget it — briquette is the practical choice.
 *  - Very low CV over a long cook: briquettes burn uniformly.
 *
 * Output: probability that the cook burned lump (0..1) + the per-
 * feature contributions so the UI can show *why* we guessed what we
 * guessed.
 */

export type FuelTypePrediction = {
  p_lump: number
  p_briquette: number
  confidence: 'low' | 'medium' | 'high'
  features: Array<{ name: string; value: number | string; contribution: number }>
  note?: string
}

/** Compute coefficient of variation (stddev / mean) on a number list. */
function cv(values: number[]): number | null {
  if (values.length < 5) return null
  const mean = values.reduce((s, v) => s + v, 0) / values.length
  if (mean <= 0) return null
  const variance = values.reduce((s, v) => s + (v - mean) ** 2, 0) / values.length
  return Math.sqrt(variance) / mean
}

/**
 * Predict lump vs briquette from a cook session.
 *
 * Requires the actual_temp_time_series to do the variance analysis.
 * Without it (historical S3-backed sessions), falls back to
 * duration/target-temp only and flags confidence as 'low'.
 */
export function predictFuelType(
  session: CookSession,
  actualTempSeries?: Array<{ t?: number; v: number }>,
): FuelTypePrediction {
  const features: Array<{ name: string; value: number | string; contribution: number }> = []
  // Start at 0 (neutral). Positive = lump-leaning, negative = briquette-leaning.
  let score = 0

  const avgTemp = session.avg_actual_temp_f ?? session.target_temp_f ?? 250
  const duration = session.duration_hours

  // Feature 1: Max temp reached — strongly distinguishing above ~425°F.
  if (avgTemp >= 425) {
    const lumpBias = Math.min(1.5, (avgTemp - 425) / 100 + 0.5)
    score += lumpBias
    features.push({ name: 'High temp (>425°F)', value: `${avgTemp.toFixed(0)}°F`, contribution: lumpBias })
  } else if (avgTemp < 275 && duration >= 6) {
    // Feature 2: Long low-and-slow cook — briquette-favored.
    const briqBias = -Math.min(1.2, (duration - 6) / 6 + 0.5)
    score += briqBias
    features.push({ name: 'Long low-and-slow', value: `${duration.toFixed(1)}h at ${avgTemp.toFixed(0)}°F`, contribution: briqBias })
  }

  // Feature 3: Temperature variance (when we have the time-series).
  let tempCv: number | null = null
  if (actualTempSeries && actualTempSeries.length > 5) {
    const vals = actualTempSeries.map(s => s.v).filter(v => v > 0 && v < 1000)
    tempCv = cv(vals)
    if (tempCv != null) {
      // CV <0.05 = very stable (briquette), >0.12 = noisy (lump)
      if (tempCv >= 0.12) {
        const contrib = Math.min(1.2, (tempCv - 0.12) * 10 + 0.5)
        score += contrib
        features.push({ name: 'High temp variance', value: `CV ${(tempCv * 100).toFixed(1)}%`, contribution: contrib })
      } else if (tempCv <= 0.05) {
        const contrib = -Math.min(1.0, (0.05 - tempCv) * 20 + 0.3)
        score += contrib
        features.push({ name: 'Flat temp profile', value: `CV ${(tempCv * 100).toFixed(1)}%`, contribution: contrib })
      } else {
        features.push({ name: 'Moderate temp variance', value: `CV ${(tempCv * 100).toFixed(1)}%`, contribution: 0 })
      }
    }
  }

  // Feature 4: Very short cook (<90 min) + very high temp — sear/grill
  // → leans lump
  if (duration <= 1.5 && avgTemp >= 400) {
    score += 0.6
    features.push({ name: 'Short hot cook', value: `${duration.toFixed(1)}h at ${avgTemp.toFixed(0)}°F`, contribution: 0.6 })
  }

  // Logistic-ish squash to [0, 1]. Scale of 2.5 gives us "strong signal"
  // at ±1.5, neutral at 0.
  const p_lump = 1 / (1 + Math.exp(-score * 1.1))
  const p_briquette = 1 - p_lump

  // Confidence: we need temp-variance data and a clear-enough score.
  let confidence: 'low' | 'medium' | 'high' = 'low'
  if (tempCv != null && Math.abs(score) >= 0.7) confidence = 'high'
  else if (tempCv != null && Math.abs(score) >= 0.3) confidence = 'medium'
  else if (Math.abs(score) >= 0.7) confidence = 'medium'

  const note = tempCv == null
    ? 'No time-series data for this cook — prediction uses duration + target only. Confidence capped at medium.'
    : undefined

  return { p_lump, p_briquette, confidence, features, note }
}

/* ─── Ambient temperature estimation ────────────────────────────────
 * Without geolocation we estimate ambient from US-wide seasonal
 * average (NOAA 30-year climate normal for CONUS). That's weak — a
 * 70°F average in April hides 90°F Phoenix vs 45°F Anchorage — but
 * it's still better than assuming 70°F year-round.
 *
 * When geo lands (via Shopify ship-zip lookup or Agustín's app data),
 * pass ``latDeg`` to get a seasonal adjustment per latitude band.
 * Future: hit a weather-history API for the exact day/location.
 */
export function estimateAmbientTempF(
  cookDateISO: string | null,
  latDeg?: number | null,
): { ambient_f: number; method: 'us_monthly_avg' | 'latitude_adjusted' | 'fallback'; note: string } {
  // Fallback when we can't parse the date.
  if (!cookDateISO) {
    return { ambient_f: 68, method: 'fallback', note: 'No cook date — using 68°F national annual average.' }
  }
  const d = new Date(cookDateISO)
  if (isNaN(d.getTime())) {
    return { ambient_f: 68, method: 'fallback', note: 'Unparseable cook date — using 68°F national annual average.' }
  }
  // CONUS monthly average (NOAA climate normal, rounded).
  // Index 0 = January.
  const CONUS_MONTHLY_F = [34, 37, 45, 54, 63, 72, 76, 75, 68, 56, 45, 36]
  const month = d.getUTCMonth()
  const base = CONUS_MONTHLY_F[month]

  if (latDeg == null) {
    return {
      ambient_f: base,
      method: 'us_monthly_avg',
      note: 'No location — using CONUS monthly climate average. ±15°F error possible.',
    }
  }

  // Rough latitude correction: every degree north of 40° → cooler by
  // ~0.8°F in summer, 1.2°F in winter. Every degree south → warmer.
  const latDelta = latDeg - 40
  const winterWeight = Math.abs(Math.cos((month - 5) * Math.PI / 6)) // strongest in Dec/Jan
  const perDegree = 0.8 + 0.4 * winterWeight
  const adjusted = base - latDelta * perDegree
  return {
    ambient_f: Math.round(adjusted),
    method: 'latitude_adjusted',
    note: `CONUS monthly avg (${base}°F) adjusted for latitude ${latDeg.toFixed(1)}°N. Still no day-specific weather.`,
  }
}

export function forecastShipments(
  lb_per_week: number,
  fuel: FuelType,
  bag_lb: number,
  lead_time_days: number,
  safety_stock_days = 7,
): ShipmentForecast {
  if (lb_per_week <= 0 || bag_lb <= 0) {
    return {
      fuel, bag_lb, lead_time_days,
      lb_per_week,
      days_per_bag: 0,
      next_ship_in_days: 0,
      upcoming_ship_dates: [],
    }
  }
  const lbPerDay = lb_per_week / 7
  const daysPerBag = bag_lb / lbPerDay
  // First ship arrives `lead_time_days` after we order. Ship when the
  // customer's remaining bag has `safety_stock_days` of burn left.
  const nextShipInDays = Math.max(0, Math.round(daysPerBag - lead_time_days - safety_stock_days))
  const upcoming: string[] = []
  const now = new Date()
  for (let i = 0; i < 6; i++) {
    const days = nextShipInDays + Math.round(daysPerBag * i)
    const d = new Date(now.getTime() + days * 86_400_000)
    upcoming.push(d.toISOString().slice(0, 10))
  }
  return {
    fuel, bag_lb, lead_time_days,
    lb_per_week,
    days_per_bag: Math.round(daysPerBag * 10) / 10,
    next_ship_in_days: nextShipInDays,
    upcoming_ship_dates: upcoming,
  }
}
