from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, defer

from app.models import CXAction, FreshdeskAgentDaily, FreshdeskTicket, IssueCluster, KPIDaily

KPI_CONFIG: dict[str, dict[str, Any]] = {
    'open_backlog': {
        'label': 'Open backlog', 'owner': 'Jeremiah', 'target': 90.0, 'red': 140.0, 'critical': 180.0,
        'title': 'Reduce active queue backlog',
        'required_action': 'Redistribute queue work immediately and clear the oldest backlog first.',
        'inverse_good': True,
    },
    'aged_tickets_24h': {
        'label': 'Aged tickets >24h', 'owner': 'Jeremiah', 'target': 50.0, 'red': 90.0, 'critical': 120.0,
        'title': 'Clear aged ticket queue',
        'required_action': 'Assign same-day ownership on aged tickets and stop new tickets from aging into the bucket.',
        'inverse_good': True,
    },
    'avg_close_time': {
        'label': 'Avg close time', 'owner': 'Jeremiah', 'target': 24.0, 'red': 48.0, 'critical': 60.0,
        'title': 'Reduce slow resolution cycle',
        'required_action': 'Review slow categories and rebalance work away from the slowest closure path.',
        'inverse_good': True,
    },
    'reopen_rate': {
        'label': 'Reopen rate', 'owner': 'Jeremiah', 'target': 5.0, 'red': 8.0, 'critical': 12.0,
        'title': 'Fix repeat-contact driver',
        'required_action': 'Audit repeat-contact tickets and fix the underlying unresolved issue.',
        'inverse_good': True,
    },
    'escalation_rate': {
        'label': 'Escalation rate', 'owner': 'Jeremiah', 'target': 8.0, 'red': 12.0, 'critical': 18.0,
        'title': 'Reduce escalation driver',
        'required_action': 'Identify escalation-heavy themes and remove the top escalation driver.',
        'inverse_good': True,
    },
    'queue_concentration_pct': {
        'label': 'Queue concentration %', 'owner': 'Jeremiah', 'target': 40.0, 'red': 50.0, 'critical': 60.0,
        'title': 'Rebalance assignment load',
        'required_action': 'Shift assignment away from the overloaded rep and rebalance queue ownership.',
        'inverse_good': True,
    },
}

HEADER_KPIS = ['closure_sla_pct', 'first_response_time', 'aged_backlog', 'support_burden']
GRID_KPIS = list(KPI_CONFIG.keys())
REP_NAMES = ['Jeremiah', 'Miles', 'Bodhi']


def _issue_is_product_linked(item: IssueCluster | None) -> bool:
    details = getattr(item, 'details_json', {}) or {}
    text = f"{getattr(item, 'title', '')} {details}".lower()
    return any(token in text for token in ['firmware', 'venom', 'temperature', 'disconnect', 'product'])


def _normalize_date(value: datetime | None) -> date | None:
    return value.date() if value else None


def _is_closed(status: str | None) -> bool:
    text = str(status or '').lower()
    return 'closed' in text or 'resolved' in text or 'solved' in text


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _pct_change(recent: list[float], prior: list[float]) -> float:
    recent_avg = _avg(recent)
    prior_avg = _avg(prior)
    if not prior or prior_avg == 0:
        return 0.0
    return ((recent_avg - prior_avg) / prior_avg) * 100.0


def _status_for(current: float, target: float, red: float) -> str:
    if current > red:
        return 'red'
    if current > target:
        return 'yellow'
    return 'green'


def _metric_period_series(rows: list[KPIDaily], tickets: list[FreshdeskTicket]) -> dict[date, dict[str, float]]:
    by_date: dict[date, dict[str, float]] = {}
    ordered_dates = [row.business_date for row in rows]
    for current_date in ordered_dates:
        start7 = ordered_dates[max(0, ordered_dates.index(current_date) - 6)]
        open_tickets = []
        aged_open_tickets = []
        recent_tickets = []
        assigned_counts: dict[str, int] = {}
        escalated = 0
        for ticket in tickets:
            created = _normalize_date(ticket.created_at_source)
            resolved = _normalize_date(ticket.resolved_at_source)
            if not created or created > current_date:
                continue
            if not (resolved and resolved <= current_date and _is_closed(ticket.status)):
                open_tickets.append(ticket)
                if created < current_date:
                    aged_open_tickets.append(ticket)
            if created >= start7 and created <= current_date:
                recent_tickets.append(ticket)
                agent = str((ticket.raw_payload or {}).get('responder_name') or ticket.agent_id or 'Unassigned')
                assigned_counts[agent] = assigned_counts.get(agent, 0) + 1
                text = f"{ticket.subject or ''} {ticket.category or ''} {' '.join(ticket.tags_json or [])}".lower()
                if any(token in text for token in ['escalat', 'engineering', 'urgent', 'firmware']):
                    escalated += 1
        total_assigned = sum(assigned_counts.values())
        queue_concentration = (max(assigned_counts.values()) / total_assigned * 100.0) if total_assigned else 0.0
        escalation_rate = (escalated / len(recent_tickets) * 100.0) if recent_tickets else 0.0
        kpi_row = next((row for row in rows if row.business_date == current_date), None)
        by_date[current_date] = {
            'open_backlog': float(kpi_row.open_backlog if kpi_row else 0.0),
            'aged_tickets_24h': float(len(aged_open_tickets)),
            'avg_close_time': float(kpi_row.resolution_time if kpi_row else 0.0),
            'reopen_rate': float(kpi_row.reopen_rate if kpi_row else 0.0),
            'escalation_rate': float(escalation_rate),
            'queue_concentration_pct': float(queue_concentration),
            'support_burden': float(kpi_row.tickets_per_100_orders if kpi_row else 0.0),
            'closure_sla_pct': float(max(0.0, 100.0 - (kpi_row.sla_breach_rate if kpi_row else 0.0))),
            'first_response_time': float(kpi_row.first_response_time if kpi_row else 0.0),
            'aged_backlog': float(len(aged_open_tickets)),
        }
    return by_date


def getCustomerExperienceMetrics(snapshot: dict[str, Any]) -> dict[str, Any]:
    series_by_date = snapshot['series_by_date']
    ordered_dates = snapshot['ordered_dates']
    if not ordered_dates:
        return {'snapshot_timestamp': None, 'header_metrics': [], 'grid_metrics': [], 'metric_map': {}, 'insights': []}
    current_date = ordered_dates[-1]
    metric_map: dict[str, dict[str, Any]] = {}

    for key in GRID_KPIS:
        config = KPI_CONFIG[key]
        values = [series_by_date[d][key] for d in ordered_dates]
        current = series_by_date[current_date][key]
        status = _status_for(current, config['target'], config['red'])
        trigger = None
        if status == 'red':
            trigger = f'{key}_gt_{int(config["red"])}'
        elif status == 'yellow':
            trigger = f'{key}_gt_{int(config["target"])}'
        consecutive_bad_days = 0
        consecutive_green_days = 0
        for d in reversed(ordered_dates):
            if series_by_date[d][key] > config['target']:
                consecutive_bad_days += 1
            else:
                break
        for d in reversed(ordered_dates):
            if series_by_date[d][key] <= config['target']:
                consecutive_green_days += 1
            else:
                break
        recent7 = values[-7:]
        prior7 = values[-14:-7]
        recent30 = values[-30:]
        prior30 = values[-60:-30]
        metric_map[key] = {
            'key': key,
            'label': config['label'],
            'owner': config['owner'],
            'current': current,
            'target': config['target'],
            'red_threshold': config['red'],
            'critical_threshold': config['critical'],
            'delta': current - config['target'],
            'trend7d': _pct_change(recent7, prior7),
            'trend30d': _pct_change(recent30, prior30),
            'status': status,
            'trigger_condition': trigger,
            'critical_immediate': current > config['critical'],
            'consecutive_bad_days': consecutive_bad_days,
            'consecutive_green_days': consecutive_green_days,
            'snapshot_timestamp': datetime.combine(current_date, datetime.min.time(), tzinfo=timezone.utc),
        }

    latest_row = snapshot['latest_row']
    header_metrics = [
        {
            'key': 'closure_sla_pct', 'label': 'Ticket Closure SLA %', 'owner': 'Jeremiah',
            'current': series_by_date[current_date]['closure_sla_pct'], 'target': 90.0,
            'delta': series_by_date[current_date]['closure_sla_pct'] - 90.0,
            'trend7d': _pct_change([series_by_date[d]['closure_sla_pct'] for d in ordered_dates[-7:]], [series_by_date[d]['closure_sla_pct'] for d in ordered_dates[-14:-7]]),
            'trend30d': _pct_change([series_by_date[d]['closure_sla_pct'] for d in ordered_dates[-30:]], [series_by_date[d]['closure_sla_pct'] for d in ordered_dates[-60:-30]]),
            'status': 'green' if series_by_date[current_date]['closure_sla_pct'] >= 90 else 'yellow' if series_by_date[current_date]['closure_sla_pct'] >= 80 else 'red',
            'confidence': 'normal', 'snapshot_timestamp': datetime.combine(current_date, datetime.min.time(), tzinfo=timezone.utc),
        },
        {
            'key': 'first_response_time', 'label': 'First Response Time', 'owner': 'Jeremiah',
            'current': series_by_date[current_date]['first_response_time'], 'target': 4.0,
            'delta': series_by_date[current_date]['first_response_time'] - 4.0,
            'trend7d': _pct_change([series_by_date[d]['first_response_time'] for d in ordered_dates[-7:]], [series_by_date[d]['first_response_time'] for d in ordered_dates[-14:-7]]),
            'trend30d': _pct_change([series_by_date[d]['first_response_time'] for d in ordered_dates[-30:]], [series_by_date[d]['first_response_time'] for d in ordered_dates[-60:-30]]),
            'status': 'green' if series_by_date[current_date]['first_response_time'] <= 4 else 'yellow' if series_by_date[current_date]['first_response_time'] <= 8 else 'red',
            'confidence': 'normal', 'snapshot_timestamp': datetime.combine(current_date, datetime.min.time(), tzinfo=timezone.utc),
        },
        {
            'key': 'aged_backlog', 'label': 'Aged Backlog', 'owner': 'Jeremiah',
            'current': series_by_date[current_date]['aged_backlog'], 'target': 50.0,
            'delta': series_by_date[current_date]['aged_backlog'] - 50.0,
            'trend7d': _pct_change([series_by_date[d]['aged_backlog'] for d in ordered_dates[-7:]], [series_by_date[d]['aged_backlog'] for d in ordered_dates[-14:-7]]),
            'trend30d': _pct_change([series_by_date[d]['aged_backlog'] for d in ordered_dates[-30:]], [series_by_date[d]['aged_backlog'] for d in ordered_dates[-60:-30]]),
            'status': 'green' if series_by_date[current_date]['aged_backlog'] <= 50 else 'yellow' if series_by_date[current_date]['aged_backlog'] <= 90 else 'red',
            'confidence': 'normal', 'snapshot_timestamp': datetime.combine(current_date, datetime.min.time(), tzinfo=timezone.utc),
        },
        {
            'key': 'support_burden', 'label': 'Support burden', 'owner': 'Jeremiah',
            'current': series_by_date[current_date]['support_burden'], 'target': 4.5,
            'delta': series_by_date[current_date]['support_burden'] - 4.5,
            'trend7d': _pct_change([series_by_date[d]['support_burden'] for d in ordered_dates[-7:]], [series_by_date[d]['support_burden'] for d in ordered_dates[-14:-7]]),
            'trend30d': _pct_change([series_by_date[d]['support_burden'] for d in ordered_dates[-30:]], [series_by_date[d]['support_burden'] for d in ordered_dates[-60:-30]]),
            'status': 'green' if series_by_date[current_date]['support_burden'] <= 4.5 else 'yellow' if series_by_date[current_date]['support_burden'] <= 7 else 'red',
            'confidence': 'low', 'snapshot_timestamp': datetime.combine(current_date, datetime.min.time(), tzinfo=timezone.utc),
        },
    ]

    concentration = metric_map['queue_concentration_pct']
    backlog = metric_map['open_backlog']
    close_time = metric_map['avg_close_time']
    reopen = metric_map['reopen_rate']
    escalation = metric_map['escalation_rate']
    top_issue = snapshot['top_issue']
    insights: list[dict[str, Any]] = []
    if concentration['status'] != 'green' and backlog['status'] != 'green':
        insights.append({
            'text': 'Queue pressure is being driven by workload concentration, not just raw ticket volume.',
            'evidence': [f"Queue concentration {concentration['current']:.1f}%", f"Open backlog {backlog['current']:.0f}", 'Top rep share exceeds target'],
            'snapshot_timestamp': metric_map['open_backlog']['snapshot_timestamp'],
        })
    if close_time['status'] != 'green' and reopen['status'] != 'green':
        insights.append({
            'text': 'Repeat-contact risk is tied to slow resolution, not just intake volume.',
            'evidence': [f"Avg close time {close_time['current']:.1f}h", f"Reopen rate {reopen['current']:.1f}%", 'Both above target in same snapshot'],
            'snapshot_timestamp': metric_map['open_backlog']['snapshot_timestamp'],
        })
    if top_issue is not None and escalation['status'] != 'green':
        insights.append({
            'text': 'Escalations are clustering around a specific issue family rather than being evenly distributed.',
            'evidence': [f"Escalation rate {escalation['current']:.1f}%", f"Top issue cluster {top_issue.title}", f"Issue owner {top_issue.owner_team or 'TBD'}"],
            'snapshot_timestamp': metric_map['open_backlog']['snapshot_timestamp'],
        })
    return {
        'snapshot_timestamp': datetime.combine(current_date, datetime.min.time(), tzinfo=timezone.utc),
        'header_metrics': header_metrics,
        'grid_metrics': [metric_map[key] for key in GRID_KPIS],
        'metric_map': metric_map,
        'insights': insights[:3],
    }


def build_customer_experience_snapshot(db: Session) -> dict[str, Any]:
    rows = db.execute(select(KPIDaily).order_by(KPIDaily.business_date)).scalars().all()
    # Defer the heavy text/JSONB columns we don't need here. Loading all
    # 9k+ ticket rows including description_text, description_html,
    # subject, and the full raw_payload JSONB was pulling ~40 MB into
    # Python and taking ~15s. None of those fields are read by cx_snapshot;
    # the only raw_payload key we need is `responder_name`, which we pull
    # in a separate small query below keyed by ticket_id.
    tickets = db.execute(
        select(FreshdeskTicket)
        .options(
            defer(FreshdeskTicket.description_text),
            defer(FreshdeskTicket.description_html),
            defer(FreshdeskTicket.subject),
            defer(FreshdeskTicket.raw_payload),
        )
        .order_by(desc(FreshdeskTicket.updated_at_source))
    ).scalars().all()
    # Responder-name lookup — one lightweight JSONB-extract query, not a
    # per-row attribute access on the heavy raw_payload blob.
    responder_rows = db.execute(
        select(
            FreshdeskTicket.ticket_id,
            FreshdeskTicket.raw_payload['responder_name'].astext.label('responder_name'),
        )
    ).all()
    responder_by_ticket: dict[str, str | None] = {r[0]: r[1] for r in responder_rows}
    agents = db.execute(select(FreshdeskAgentDaily).order_by(FreshdeskAgentDaily.business_date, FreshdeskAgentDaily.agent_name, FreshdeskAgentDaily.agent_id)).scalars().all()
    top_issue = db.execute(select(IssueCluster).order_by(desc(IssueCluster.updated_at), desc(IssueCluster.id)).limit(1)).scalar_one_or_none()
    product_linked = _issue_is_product_linked(top_issue)
    ordered_dates = [row.business_date for row in rows]
    latest_row = rows[-1] if rows else None
    series_by_date = _metric_period_series(rows, tickets) if rows else {}
    base_snapshot = {
        'rows': rows,
        'tickets': tickets,
        'agents': agents,
        'ordered_dates': ordered_dates,
        'latest_row': latest_row,
        'series_by_date': series_by_date,
        'top_issue': top_issue,
        'product_linked': product_linked,
    }
    metrics = getCustomerExperienceMetrics(base_snapshot)
    snapshot_timestamp = metrics['snapshot_timestamp']
    if snapshot_timestamp is None:
        return {
            'snapshot_timestamp': None,
            'header_metrics': [],
            'grid_metrics': [],
            'team_load': [],
            'insights': [],
            'actions': [],
            'today_focus': [],
            'product_linked': product_linked,
        }
    snapshot_date = snapshot_timestamp.date()
    start7 = ordered_dates[max(0, len(ordered_dates) - 7)] if ordered_dates else snapshot_date
    snapshot_open_tickets = []
    for ticket in tickets:
        created = _normalize_date(ticket.created_at_source)
        resolved = _normalize_date(ticket.resolved_at_source)
        if not created or created > snapshot_date:
            continue
        if resolved and resolved <= snapshot_date and _is_closed(ticket.status):
            continue
        snapshot_open_tickets.append(ticket)
    open_by_rep: dict[str, int] = defaultdict(int)
    assigned_map: dict[str, int] = defaultdict(int)
    reopened_map: dict[str, dict[str, int]] = defaultdict(lambda: {'total': 0, 'reopened': 0})
    for ticket in snapshot_open_tickets:
        name = str(responder_by_ticket.get(ticket.ticket_id) or ticket.agent_id or 'Unassigned')
        open_by_rep[name] += 1
    for ticket in tickets:
        created = _normalize_date(ticket.created_at_source)
        if not created or created < start7 or created > snapshot_date:
            continue
        name = str(responder_by_ticket.get(ticket.ticket_id) or ticket.agent_id or 'Unassigned')
        assigned_map[name] += 1
        reopened_map[name]['total'] += 1
        text = f"{ticket.category or ''} {' '.join(ticket.tags_json or [])}".lower()
        if 'reopen' in text or 're-open' in text:
            reopened_map[name]['reopened'] += 1
    resolved_map: dict[str, dict[str, Any]] = defaultdict(lambda: {'resolved': 0, 'resolution_hours': []})
    for agent in agents:
        if agent.business_date < start7 or agent.business_date > snapshot_date:
            continue
        name = str(agent.agent_name or agent.agent_id or 'Unassigned')
        resolved_map[name]['resolved'] += int(agent.tickets_resolved or 0)
        if (agent.resolution_hours or 0) > 0:
            resolved_map[name]['resolution_hours'].append(float(agent.resolution_hours or 0))
    total_assigned = sum(assigned_map.values())
    team_load = []
    for rep in REP_NAMES:
        assigned = next((v for k, v in assigned_map.items() if rep.lower() in k.lower()), 0)
        active_queue_size = next((v for k, v in open_by_rep.items() if rep.lower() in k.lower()), 0)
        resolved = next((v['resolved'] for k, v in resolved_map.items() if rep.lower() in k.lower()), 0)
        resolution_hours = next((v['resolution_hours'] for k, v in resolved_map.items() if rep.lower() in k.lower()), [])
        reopen_row = next((v for k, v in reopened_map.items() if rep.lower() in k.lower()), {'total': 0, 'reopened': 0})
        team_load.append({
            'name': rep,
            'tickets_closed_per_day': resolved / 7 if start7 else 0,
            'active_queue_size': active_queue_size,
            'throughput_ratio': (resolved / assigned) if assigned else 0,
            'avg_close_time': _avg(resolution_hours),
            'reopen_rate': (reopen_row['reopened'] / reopen_row['total'] * 100) if reopen_row['total'] else 0,
            'share_pct': (assigned / total_assigned * 100) if total_assigned else 0,
            'snapshot_timestamp': snapshot_timestamp,
        })
    all_actions = db.execute(select(CXAction).order_by(desc(CXAction.updated_at))).scalars().all()
    actions = [action for action in all_actions if action.snapshot_timestamp == snapshot_timestamp]
    open_actions = [action for action in actions if action.status != 'resolved']
    def _priority_score(action: CXAction) -> int:
        base = {'critical': 100, 'high': 70, 'medium': 40, 'low': 20}.get(action.priority, 20)
        if action.escalation_owner:
            base += 20
        return base
    open_actions = sorted(open_actions, key=_priority_score, reverse=True)
    return {
        'snapshot_timestamp': snapshot_timestamp,
        'header_metrics': metrics['header_metrics'],
        'grid_metrics': metrics['grid_metrics'],
        'team_load': team_load,
        'insights': metrics['insights'],
        'actions': actions,
        'today_focus': open_actions[:3],
        'product_linked': product_linked,
    }
