import { useEffect, useMemo, useRef, useState } from 'react'
import { ActionBlock } from '../components/ActionBlock'
import { BaselineBand } from '../components/BaselineBand'
import { Card } from '../components/Card'
import { GrossProfitCard } from '../components/GrossProfitCard'
import { EmailPulseCard } from '../components/EmailPulseCard'
import { BetaProgramSummaryCard } from '../components/BetaProgramSummaryCard'
import { EventTimelinePanel } from '../components/EventTimelinePanel'
import { EventTimelineStrip } from '../components/EventTimelineStrip'
import { KpiGrid } from '../components/KpiGrid'
import { MetricProvenancePanel, MetricProvenanceItem } from '../components/MetricProvenancePanel'
import { RangeToolbar } from '../components/RangeToolbar'
import { StaleDataBanner } from '../components/StaleDataBanner'
import { TrendChart } from '../components/TrendChart'
import { EventAnnotationList } from '../components/EventAnnotationList'
import { StatePanel } from '../components/StatePanel'
import { ThresholdPanel } from '../components/ThresholdPanel'
import { CollapsibleSection } from '../components/CollapsibleSection'
import { ApiError, api } from '../lib/api'
import { buildPresetRange, businessTodayDate, filterRowsByRange, summarizeKpis, summarizeRangeLabel, RangeState } from '../lib/range'
import { ACTIVE_CONNECTORS, isTruthfullyHealthy, isScaffolded } from '../lib/sourceHealth'
import { useUrlRange } from '../lib/urlRange'
import { DataQualityResponse, IntradayStatus, KPIIntraday, KPIDaily, KpiDisplayMode, KpiDisplayRow, OverviewResponse, SourceHealthItem } from '../lib/types'

function truthyConnectorRows(rows: SourceHealthItem[]) {
  return rows.filter((row) => ACTIVE_CONNECTORS.has(row.source))
}

function getIntradayStatus(intraday: KPIIntraday | null, latestCompleteDay?: KPIDaily): { status: IntradayStatus; message: string } {
  if (!intraday) {
    return { status: 'unavailable', message: 'Intraday feed unavailable.' }
  }
  if (intraday.sessions === 0 && intraday.orders > 0) {
    return { status: 'partial', message: 'Data not yet available for sessions; showing partial intraday data instead of misleading zero activity.' }
  }
  if (latestCompleteDay && intraday.sessions < latestCompleteDay.sessions * 0.1) {
    return { status: 'delayed', message: 'Intraday feed appears delayed relative to the latest complete day.' }
  }
  return { status: 'live', message: 'Live intraday signal available.' }
}

function dataQualitySeverity(row: Record<string, unknown>) {
  if (Array.isArray(row.warnings) && row.warnings.length) return 'bad'
  const sessionsPctDiff = typeof row.sessions_pct_diff === 'number' ? row.sessions_pct_diff : null
  const ordersPctDiff = typeof row.orders_vs_purchases_pct_diff === 'number' ? row.orders_vs_purchases_pct_diff : null
  const maxDiff = Math.max(Math.abs(sessionsPctDiff ?? 0), Math.abs(ordersPctDiff ?? 0))
  if (maxDiff >= 100) return 'bad'
  if (maxDiff >= 25 || row.type === 'shopify_sessions_missing') return 'warn'
  return 'good'
}

function isIncompleteLatestDay(row?: KPIDaily) {
  if (!row) return false
  return (row.sessions === 0 || row.sessions == null) && ((row.orders || 0) > 0 || (row.revenue || 0) > 0)
}

export function ExecutiveOverview() {
  const todayDate = businessTodayDate()
  const [data, setData] = useState<OverviewResponse | null>(null)
  const [intraday, setIntraday] = useState<KPIIntraday | null>(null)
  const [intradaySeries, setIntradaySeries] = useState<Array<{ bucket_start: string; business_date: string; hour_label: string; revenue: number; sessions: number; orders: number }>>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [dataQuality, setDataQuality] = useState<DataQualityResponse | null>(null)
  const [intradayError, setIntradayError] = useState<string | null>(null)
  const [dataQualityError, setDataQualityError] = useState<string | null>(null)
  const [range, setRange] = useState<RangeState>({ preset: '7d', startDate: '', endDate: '' })
  const requestIdRef = useRef(0)
  const hydratedRangeRef = useRef(false)

  useUrlRange(range, (nextRange) => {
    if (hydratedRangeRef.current) return
    hydratedRangeRef.current = true
    setRange(nextRange)
  })

  function sanitizeDailyRows(rows: KPIDaily[]) {
    if (!rows.length) return rows
    return isIncompleteLatestDay(rows[rows.length - 1]) ? rows.slice(0, -1) : rows
  }

  async function load(signal?: AbortSignal) {
      const requestId = ++requestIdRef.current
      setLoading(true)
      setError(null)
      setIntradayError(null)
      setDataQualityError(null)
      const [overviewPayload, intradayPayload, intradaySeriesPayload, dataQualityPayload] = await Promise.allSettled([
        api.overview(signal),
        api.currentKpi(signal),
        api.intradaySeries(signal),
        api.dataQuality(signal),
      ])

      if (signal?.aborted || requestId !== requestIdRef.current) return

      if (overviewPayload.status === 'fulfilled') {
          const orderedSeries = [...(overviewPayload.value.daily_series || [])].sort((a, b) => a.business_date.localeCompare(b.business_date))
          const safeSeries = sanitizeDailyRows(orderedSeries)
          setData({ ...overviewPayload.value, daily_series: orderedSeries })
          setRange((current) => current.startDate && current.endDate ? current : buildPresetRange('7d', safeSeries, { anchorDate: todayDate }))
      } else {
        setData(null)
        setError(overviewPayload.reason instanceof ApiError ? overviewPayload.reason.message : 'Failed to load overview')
      }

      if (intradayPayload.status === 'fulfilled') {
        setIntraday(intradayPayload.value)
      } else {
        setIntraday(null)
        setIntradayError(intradayPayload.reason instanceof ApiError ? intradayPayload.reason.message : 'Failed to load intraday KPI')
      }

      if (intradaySeriesPayload.status === 'fulfilled') {
        setIntradaySeries(intradaySeriesPayload.value.rows || [])
      } else {
        setIntradaySeries([])
        setIntradayError((current) => current || (intradaySeriesPayload.reason instanceof ApiError ? intradaySeriesPayload.reason.message : 'Failed to load intraday series'))
      }

      if (dataQualityPayload.status === 'fulfilled') {
        setDataQuality(dataQualityPayload.value)
      } else {
        setDataQuality(null)
        setDataQualityError(dataQualityPayload.reason instanceof ApiError ? dataQualityPayload.reason.message : 'Failed to load data quality')
      }

      setLoading(false)
  }

  useEffect(() => {
    const controller = new AbortController()
    load(controller.signal).catch((err) => {
      if (controller.signal.aborted) return
      if (requestIdRef.current === 0) return
      setLoading(false)
      setError(err instanceof ApiError ? err.message : 'Failed to load overview')
    })
    return () => {
      controller.abort()
      requestIdRef.current += 1
    }
  }, [])

  const safeDailyRows = useMemo(() => sanitizeDailyRows(data?.daily_series || []), [data])
  const rangeRows = useMemo(() => filterRowsByRange(safeDailyRows, range), [safeDailyRows, range])
  const rangeSummary = useMemo(() => summarizeKpis(rangeRows), [rangeRows])
  const latestIntradayDate = useMemo(() => intradaySeries.at(-1)?.business_date || intraday?.bucket_start?.slice(0, 10) || safeDailyRows.at(-1)?.business_date, [intradaySeries, intraday, safeDailyRows])
  const todaysIntradaySeries = useMemo(() => {
    if (range.preset !== 'today') return intradaySeries
    const targetDate = todayDate
    return intradaySeries.filter((row) => row.business_date === targetDate)
  }, [intradaySeries, range, todayDate])
  const todaySeriesSummary = useMemo(() => {
    if (!todaysIntradaySeries.length) return undefined
    const latestRow = todaysIntradaySeries[todaysIntradaySeries.length - 1]
    const revenue = Number(latestRow.revenue || 0)
    const sessions = Number(latestRow.sessions || 0)
    const orders = Number(latestRow.orders || 0)
    const matchingDailyRow = safeDailyRows.find((row) => row.business_date === todayDate)
    const adSpend = matchingDailyRow?.ad_spend ?? null
    return {
      business_date: todayDate,
      revenue,
      orders,
      average_order_value: orders ? revenue / orders : 0,
      sessions,
      conversion_rate: sessions ? (orders / sessions) * 100 : 0,
      revenue_per_session: sessions ? revenue / sessions : 0,
      add_to_cart_rate: matchingDailyRow?.add_to_cart_rate ?? null,
      bounce_rate: matchingDailyRow?.bounce_rate ?? null,
      purchases: matchingDailyRow?.purchases ?? orders,
      ad_spend: adSpend,
      mer: adSpend ? revenue / adSpend : null,
      cost_per_purchase: adSpend && orders ? adSpend / orders : null,
      tickets_created: matchingDailyRow?.tickets_created ?? null,
      tickets_resolved: matchingDailyRow?.tickets_resolved ?? null,
      open_backlog: matchingDailyRow?.open_backlog ?? null,
      first_response_time: matchingDailyRow?.first_response_time ?? null,
      resolution_time: matchingDailyRow?.resolution_time ?? null,
      sla_breach_rate: matchingDailyRow?.sla_breach_rate ?? null,
      csat: matchingDailyRow?.csat ?? null,
      reopen_rate: matchingDailyRow?.reopen_rate ?? null,
      tickets_per_100_orders: matchingDailyRow?.tickets_per_100_orders ?? null,
      revenue_source: 'intraday_snapshot',
      sessions_source: 'intraday_snapshot',
      orders_source: 'shopify',
      is_partial_day: true,
      is_fallback_day: false,
    } as KpiDisplayRow
  }, [todaysIntradaySeries, todayDate, safeDailyRows])
  const latestCompleteDay = useMemo(() => {
    if (data?.latest_kpi) return data.latest_kpi
    const rows = data?.daily_series || []
    return [...rows].reverse().find((row) => !isIncompleteLatestDay(row))
  }, [data])
  const sourceHealth = data?.source_health || []
  const liveConnectors = truthyConnectorRows(sourceHealth)
  const scaffoldedCount = sourceHealth.filter((row) => isScaffolded(row)).length

  const displayMode: KpiDisplayMode = range.preset === 'today' ? 'today_intraday' : rangeSummary ? 'selected_range_summary' : latestCompleteDay ? 'latest_complete_day' : 'today_intraday'
  const displayKpi: KpiDisplayRow | undefined = range.preset === 'today'
    ? todaySeriesSummary
    : (rangeSummary || latestCompleteDay)
  const displayIntraday = range.preset === 'today'
    ? (todaySeriesSummary
        ? {
            revenue: todaySeriesSummary.revenue,
            orders: todaySeriesSummary.orders,
            sessions: todaySeriesSummary.sessions,
            average_order_value: todaySeriesSummary.average_order_value,
            conversion_rate: todaySeriesSummary.conversion_rate,
          }
        : null)
    : intraday
  const computedIntradayState = getIntradayStatus(displayIntraday, latestCompleteDay)
  const intradayState = range.preset === 'today' && intradayError && !todaysIntradaySeries.length
    ? { status: 'unavailable' as IntradayStatus, message: `Intraday feed unavailable; switch to 7d or latest complete day. ${intradayError}` }
    : range.preset === 'today' && intradayError && todaysIntradaySeries.length
      ? { status: 'partial' as IntradayStatus, message: `Intraday summary endpoint failed, but hourly series is available. ${intradayError}` }
      : computedIntradayState
  const scopeLabel = summarizeRangeLabel(range)
  const provenanceItems: MetricProvenanceItem[] = [
    {
      metric: 'Revenue',
      sourceSystem: 'Shopify via backend /api/overview',
      queryLogic: 'overview.daily_series -> summarize selected range',
      timeWindow: scopeLabel,
      refreshCadence: 'poll + webhook backed sync, visible in source health',
      transformationLogic: 'selected-range sum of kpi_daily.revenue',
      caveats: displayKpi?.is_partial_day ? 'Partial-day or intraday values may be incomplete.' : 'Dependent on current Shopify truth rebuild path.',
    },
    {
      metric: 'Orders',
      sourceSystem: 'Shopify via backend /api/overview',
      queryLogic: 'overview.daily_series -> summarize selected range',
      timeWindow: scopeLabel,
      refreshCadence: 'poll + webhook backed sync, visible in source health',
      transformationLogic: 'selected-range sum of kpi_daily.orders',
      caveats: 'Order counts inherit backend business-date attribution and latest-order-state logic.',
    },
    {
      metric: 'Sessions',
      sourceSystem: 'Triple Whale via backend /api/overview',
      queryLogic: 'overview.daily_series sessions field',
      timeWindow: scopeLabel,
      refreshCadence: 'poll sync, visible in source health',
      transformationLogic: 'selected-range sum of kpi_daily.sessions',
      caveats: 'If intraday sessions lag, UI marks partial/unavailable instead of silently showing zero.',
    },
  ]
  const actionItems = [
    liveConnectors.some((row) => row.derived_status !== 'healthy') ? 'Resolve stale or failed connectors before acting on directional changes.' : 'Live connectors are healthy; use movement in revenue, sessions, and orders as decision-grade signals.',
    rangeRows.length < 3 ? 'Widen the date range before making directional decisions; current window is too thin.' : 'Compare this range against the prior period before making budget or channel changes.',
    (data?.alerts?.[0]?.message || data?.recommendations?.[0]?.recommended_action) ? `First priority: ${data?.recommendations?.[0]?.recommended_action || data?.alerts?.[0]?.message}` : 'No priority recommendation returned; inspect Diagnostics and Source Health before changing operations.',
  ]

  return (
    <div className="page-grid">
      <div className="page-head">
        <h2>Executive Overview</h2>
        <p>Truthful KPI scope, clear intraday status, and source health that reflects what is actually live.</p>
      </div>

      <RangeToolbar rows={safeDailyRows} range={range} onChange={setRange} anchorDate={todayDate} />
      <StaleDataBanner rows={liveConnectors} />

      {loading ? <Card title="Overview Status"><div className="state-message">Loading live backend data…</div></Card> : null}
      {error ? <Card title="Overview Error"><div className="state-message error">{error}</div><button className="button" onClick={() => void load()}>Retry</button></Card> : null}

      {!loading && !error && data ? (
        <>
          <KpiGrid latest={displayKpi} intraday={displayIntraday} scopeLabel={scopeLabel} displayMode={displayMode} intradayStatus={intradayState.status} intradayMessage={range.preset === 'today' ? (intradayError ? `Intraday feed unavailable; switch to 7d or latest complete day. ${intradayError}` : todaySeriesSummary ? `As of ${todaysIntradaySeries[todaysIntradaySeries.length - 1]?.hour_label || 'latest bucket'} · Today banner, KPI cards, and charts all use the same filtered hourly intraday series.` : 'No intraday data available') : intradayState.message} noDataMessage={range.preset === 'today' ? 'No intraday data available' : 'No KPI summary returned.'} sourceHealth={liveConnectors} />
          <GrossProfitCard days={30} />
          <ActionBlock items={actionItems} />
          <CollapsibleSection
            id="exec-thresholds"
            title="Threshold tripwires"
            subtitle="Per-metric warning + escalation thresholds"
            density="compact"
          >
            <ThresholdPanel metrics={[
              { metric: 'conversion_rate', value: displayKpi?.conversion_rate },
              { metric: 'mer', value: displayKpi?.mer },
              { metric: 'average_order_value', value: displayKpi?.average_order_value },
              { metric: 'bounce_rate', value: displayKpi?.bounce_rate },
              { metric: 'open_backlog', value: displayKpi?.open_backlog },
              { metric: 'tickets_per_100_orders', value: displayKpi?.tickets_per_100_orders },
              { metric: 'first_response_time', value: displayKpi?.first_response_time },
            ]} />
          </CollapsibleSection>
          <CollapsibleSection
            id="exec-provenance"
            title="Why these numbers"
            subtitle="Per-metric provenance — source pipeline, calculation, freshness"
            density="compact"
          >
            <MetricProvenancePanel items={provenanceItems} />
          </CollapsibleSection>
          <div className="two-col two-col-equal">
            <Card title="Revenue + Sessions Trend">
              {range.preset === 'today' ? (
                todaysIntradaySeries.length ? (
                  <TrendChart
                    rows={todaysIntradaySeries.map((row) => ({ business_date: row.hour_label, revenue: row.revenue, sessions: row.sessions, orders: row.orders } as KPIDaily))}
                    lines={[
                      { key: 'revenue', label: 'Revenue', color: '#6ea8ff', axisId: 'left' },
                      { key: 'sessions', label: 'Sessions', color: '#ffb257', axisId: 'right' },
                    ]}
                  />
                ) : <div className="state-message">No KPI rows available for selected range</div>
              ) : rangeRows.length ? (
                <TrendChart
                  rows={rangeRows}
                  lines={[
                    { key: 'revenue', label: 'Revenue', color: '#6ea8ff', axisId: 'left' },
                    { key: 'sessions', label: 'Sessions', color: '#ffb257', axisId: 'right' },
                  ]}
                />
              ) : <div className="state-message">No KPI rows available for selected range</div>}
            </Card>
            <Card title="Orders Trend">
              {range.preset === 'today' ? (
                todaysIntradaySeries.length ? (
                  <TrendChart
                    rows={todaysIntradaySeries.map((row) => ({ business_date: row.hour_label, revenue: row.revenue, sessions: row.sessions, orders: row.orders } as KPIDaily))}
                    lines={[{ key: 'orders', label: 'Orders', color: '#39d08f', axisId: 'left' }]}
                    height={220}
                  />
                ) : <div className="state-message">No KPI rows available for selected range</div>
              ) : rangeRows.length ? (
                <TrendChart
                  rows={rangeRows}
                  lines={[{ key: 'orders', label: 'Orders', color: '#39d08f', axisId: 'left' }]}
                  height={220}
                />
              ) : <div className="state-message">No KPI rows available for selected range</div>}
            </Card>
          </div>
          {range.preset !== 'today' && range.startDate && range.endDate && rangeRows.length ? (
            <Card title="Revenue vs Seasonal Baseline">
              <BaselineBand
                metric="revenue"
                start={range.startDate}
                end={range.endDate}
                currentSeries={rangeRows.map((r) => ({ date: r.business_date, value: r.revenue }))}
                currentLabel="Revenue"
                color="#6ea8ff"
                valueFormatter={(v) => `$${Math.round(v).toLocaleString()}`}
              />
              <div style={{ marginTop: 10 }}>
                <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>
                  Events during this window:
                </div>
                <EventTimelineStrip
                  start={range.startDate}
                  end={range.endDate}
                  showStates={false}
                />
              </div>
            </Card>
          ) : null}
          {range.startDate && range.endDate ? (
            <EventTimelinePanel
              title="Company event timeline"
              defaultStart={range.startDate}
              defaultEnd={range.endDate}
            />
          ) : null}
          {/* Alerts + Recommendations merged — same render shape, same source of truth. */}
          <Card title="Alerts & recommendations">
            <div className="stack-list">
              {(data?.alerts || []).slice(0, 3).map((alert) => (
                <div className="list-item status-warn" key={`a-${alert.id}`}>
                  <strong>⚠ {alert.title}</strong>
                  <p>{alert.message}</p>
                </div>
              ))}
              {(data?.recommendations || []).slice(0, 3).map((item) => (
                <div className="list-item" key={`r-${item.id}`}>
                  <strong>{item.title}</strong>
                  <p>{item.recommended_action}</p>
                </div>
              ))}
              {!data?.alerts?.length && !data?.recommendations?.length ? (
                <div className="state-message">No alerts or recommendations returned.</div>
              ) : null}
            </div>
          </Card>

          <CollapsibleSection
            id="exec-source-health"
            title="Source health snapshot"
            subtitle="Per-connector live/configured state · drill in when StaleDataBanner is red"
            density="compact"
            meta={`${liveConnectors.filter(isTruthfullyHealthy).length}/${liveConnectors.length} healthy`}
          >
            <div className="stack-list">
              {liveConnectors.map((item) => {
                const truthfulHealthy = isTruthfullyHealthy(item)
                return (
                  <div className={`list-item ${truthfulHealthy ? 'status-good' : ''}`} key={item.source}>
                    <div className="item-head">
                      <strong>{item.source}</strong>
                      <div className="inline-badges">
                        <span className={`badge ${item.configured && item.latest_run_status === 'success' ? 'badge-good' : item.configured ? 'badge-neutral' : 'badge-warn'}`}>
                          {item.configured && item.latest_run_status === 'success' ? 'Live' : item.configured ? 'Configured' : 'Not configured'}
                        </span>
                        <span className={`badge ${truthfulHealthy ? 'badge-good' : 'badge-neutral'}`}>{truthfulHealthy ? 'healthy' : item.derived_status}</span>
                      </div>
                    </div>
                    <p>{truthfulHealthy ? 'Recent successful sync exists. Showing live connector as healthy.' : item.status_summary}</p>
                    <small>Latest run: {item.latest_run_status} · Records: {item.latest_records_processed}</small>
                  </div>
                )
              })}
              <div className="list-item scaffold-source">
                <div className="item-head">
                  <strong>Scaffolded future sources</strong>
                  <span className="badge badge-muted">Scaffolded</span>
                </div>
                <p>{scaffoldedCount} intentionally disabled / not yet live sources are excluded from live connector health.</p>
              </div>
            </div>
          </CollapsibleSection>

          <CollapsibleSection
            id="exec-data-quality"
            title="Data quality visibility"
            subtitle="Partial days, fallback sources, drift warnings, validation issues"
            density="compact"
          >
            <div className="stack-list">
              {displayKpi?.is_partial_day ? (
                <StatePanel kind="partial" tone="warn" title="Selected KPI window includes partial data" message="At least one displayed KPI row is partial-day or intraday. Treat short-window movement as directional until the next complete business day lands." />
              ) : null}
              {displayKpi?.is_fallback_day ? (
                <StatePanel kind="partial" tone="warn" title="Fallback source used in selected window" message="At least one KPI row relied on fallback source logic. Use source health and provenance before making irreversible decisions." />
              ) : null}
              {dataQualityError ? (
                <div className="list-item status-warn">
                  <strong>Data quality feed unavailable</strong>
                  <p>{dataQualityError}</p>
                  <button className="button" onClick={() => void load()}>Retry</button>
                </div>
              ) : null}
              {(dataQuality?.missing_data || []).map((item, index) => (
                <div className={`list-item status-${dataQualitySeverity(item)}`} key={`missing-${index}`}>
                  <strong>Missing data</strong>
                  <p>{String(item.message || 'Missing data note')}</p>
                  <small>{String(item.business_date || 'n/a')}</small>
                </div>
              ))}
              {(dataQuality?.source_drift || []).slice(0, 5).map((item, index) => (
                <div className={`list-item status-${dataQualitySeverity(item)}`} key={`drift-${index}`}>
                  <strong>Source drift</strong>
                  <p>{String(item.business_date || 'n/a')}</p>
                  <small>Sessions drift: {String(item.sessions_pct_diff ?? 'n/a')}% · Orders vs purchases drift: {String(item.orders_vs_purchases_pct_diff ?? 'n/a')}%</small>
                </div>
              ))}
              {(dataQuality?.validation_warnings || []).map((item, index) => (
                <div className={`list-item status-${dataQualitySeverity(item)}`} key={`validation-${index}`}>
                  <strong>Validation warning</strong>
                  <p>{Array.isArray(item.warnings) ? item.warnings.join(' · ') : 'Validation mismatch detected'}</p>
                  <small>{String(item.business_date || 'n/a')}</small>
                </div>
              ))}
              {!dataQualityError && dataQuality && !dataQuality.missing_data.length && !dataQuality.source_drift.length && !dataQuality.validation_warnings.length ? (
                <div className="list-item status-good">
                  <strong>Data quality</strong>
                  <p>No data-quality warnings returned.</p>
                </div>
              ) : null}
            </div>
          </CollapsibleSection>
          {range.startDate && range.endDate ? (
            <EmailPulseCard range={{ startDate: range.startDate, endDate: range.endDate }} />
          ) : null}
          <BetaProgramSummaryCard />
          <CollapsibleSection
            id="exec-event-annotations"
            title="Decision event annotations"
            subtitle="Diagnostics + recommendations rendered against the active window"
            density="compact"
          >
            <EventAnnotationList diagnostics={data?.diagnostics || []} recommendations={data?.recommendations || []} rangeStart={range.startDate} rangeEnd={range.endDate} />
          </CollapsibleSection>
          <CollapsibleSection
            id="exec-inventory-risk"
            title="Inventory / fulfillment risk layer"
            subtitle="ERP integration status — blocked until Business Central lands"
            density="compact"
          >
            {sourceHealth.some((row) => row.source === 'business_central' || row.source === 'dynamics') ? (
              <StatePanel kind="partial" tone="warn" title="ERP risk layer not decision-grade yet" message="Inventory / fulfillment connector rows exist but this page still needs connector-backed stockout, aging, and fulfillment latency metrics before operators should trust it." />
            ) : (
              <StatePanel kind="partial" tone="warn" title="ERP inventory layer blocked" message="Dynamics / Business Central is not live in source health yet, so inventory and fulfillment risk are still blind spots. Do not treat the executive page as complete for ops decisions." detail="Required next layer: stockout risk, open PO coverage, fulfillment aging, and ship-delay burden by SKU/family." />
            )}
          </CollapsibleSection>
        </>
      ) : null}
    </div>
  )
}
