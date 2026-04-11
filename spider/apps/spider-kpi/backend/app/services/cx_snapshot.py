from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import CXAction, FreshdeskAgentDaily, FreshdeskTicket, IssueCluster, KPIDaily

KPI_CONFIG: dict[str, dict[str, Any]] = {
    # Primary focus: How quickly we respond to customers (not closure time)
    'avg_response_time': {
        'label': 'Avg response time', 'owner': 'Jeremiah', 'target': 4.0, 'red': 8.0, 'critical': 12.0,
        'title': 'Improve team response speed',
        'required_action': 'Prioritize first touch on waiting tickets. Aim for sub-4-hour initial response.',
        'inverse_good': True,
    },
    # Only tickets where customer is waiting on US (not customer-owned tickets)
    'awaiting_team_reply': {
        'label': 'Awaiting our reply', 'owner': 'Jeremiah', 'target': 30.0, 'red': 50.0, 'critical': 70.0,
        'title': 'Clear team-owned backlog',
        'required_action': 'Focus on tickets where customer is waiting on us, not tickets waiting on customer.',
        'inverse_good': True,
    },
    # Total open (context only - not penalized for customer-owned tickets)
    'open_backlog': {
        'label': 'Total open tickets', 'owner': 'Jeremiah', 'target': 120.0, 'red': 180.0, 'critical': 220.0,
        'title': 'Monitor total queue size',
        'required_action': 'Review queue composition: customer-owned vs team-owned. Prioritize team-owned.',
        'inverse_good': True,
    },
    # Track engagement depth - meaningful interactions per ticket
    'engagement_depth': {
        'label': 'Engagement depth', 'owner': 'Jeremiah', 'target': 2.5, 'red': 1.5, 'critical': 1.0,
        'title': 'Ensure thorough customer engagement',
        'required_action': 'Low engagement may indicate rushed responses. Review ticket quality.',
        'inverse_good': False,  # Higher is better
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


def _status_for(current: float, target: float, red: float, inverse_good: bool = True) -> str:
    """Determine status based on thresholds. inverse_good=True means lower is better."""
    if inverse_good:
        if current > red:
            return 'red'
        if current > target:
            return 'yellow'
        return 'green'
    else:
        # Higher is better (e.g., engagement depth)
        if current < red:
            return 'red'
        if current < target:
            return 'yellow'
        return 'green'


def _is_customer_owned(ticket: FreshdeskTicket) -> bool:
    """Determine if ticket is currently owned by customer (waiting on their reply).

    Freshdesk status codes:
    - 2 = Open (team-owned, waiting on agent)
    - 3 = Pending (customer-owned, waiting on customer reply)
    - 4 = Resolved
    - 5 = Closed

    We consider a ticket "customer-owned" if it's in Pending status.
    """
    status = str(ticket.status or '').lower()
    # Pending status means customer needs to respond
    if 'pending' in status or status == '3':
        return True
    # Open status means team needs to respond
    return False


def _estimate_engagement_depth(ticket: FreshdeskTicket) -> float:
    """Estimate engagement depth from ticket metadata.

    Uses raw_payload stats to estimate number of interactions.
    Higher engagement depth indicates more thorough customer support.
    """
    raw = ticket.raw_payload or {}
    stats = raw.get('stats', {})

    # Try to get reply count from various possible fields
    agent_responded_at = stats.get('agent_responded_at')
    first_responded_at = stats.get('first_responded_at')

    # Estimate based on resolution hours vs first response
    # If resolution took much longer than first response, likely more interactions
    fr_hours = ticket.first_response_hours or 0
    res_hours = ticket.resolution_hours or 0

    if res_hours > 0 and fr_hours > 0:
        # Rough heuristic: more time = more interactions
        interaction_ratio = res_hours / max(fr_hours, 1)
        return min(max(1.0, interaction_ratio * 0.5), 10.0)

    # Default baseline engagement
    return 2.0


def _metric_period_series(rows: list[KPIDaily], tickets: list[FreshdeskTicket]) -> dict[date, dict[str, float]]:
    by_date: dict[date, dict[str, float]] = {}
    ordered_dates = [row.business_date for row in rows]
    for current_date in ordered_dates:
        start7 = ordered_dates[max(0, ordered_dates.index(current_date) - 6)]
        open_tickets = []
        team_owned_tickets = []  # Tickets waiting on US (not customer)
        recent_tickets = []
        assigned_counts: dict[str, int] = {}
        escalated = 0
        response_times: list[float] = []
        engagement_scores: list[float] = []

        for ticket in tickets:
            created = _normalize_date(ticket.created_at_source)
            resolved = _normalize_date(ticket.resolved_at_source)
            if not created or created > current_date:
                continue

            # Track open tickets
            if not (resolved and resolved <= current_date and _is_closed(ticket.status)):
                open_tickets.append(ticket)
                # Only count as team-owned if NOT customer-pending
                if not _is_customer_owned(ticket):
                    team_owned_tickets.append(ticket)

            # Track recent tickets for other metrics
            if created >= start7 and created <= current_date:
                recent_tickets.append(ticket)
                agent = str((ticket.raw_payload or {}).get('responder_name') or ticket.agent_id or 'Unassigned')
                assigned_counts[agent] = assigned_counts.get(agent, 0) + 1

                # Track response times (what we really care about)
                if ticket.first_response_hours and ticket.first_response_hours > 0:
                    response_times.append(ticket.first_response_hours)

                # Track engagement depth
                engagement_scores.append(_estimate_engagement_depth(ticket))

                # Track escalations
                text = f"{ticket.subject or ''} {ticket.category or ''} {' '.join(ticket.tags_json or [])}".lower()
                if any(token in text for token in ['escalat', 'engineering', 'urgent', 'firmware']):
                    escalated += 1

        total_assigned = sum(assigned_counts.values())
        queue_concentration = (max(assigned_counts.values()) / total_assigned * 100.0) if total_assigned and assigned_counts else 0.0
        escalation_rate = (escalated / len(recent_tickets) * 100.0) if recent_tickets else 0.0
        avg_response_time = _avg(response_times) if response_times else 0.0
        avg_engagement = _avg(engagement_scores) if engagement_scores else 2.0

        kpi_row = next((row for row in rows if row.business_date == current_date), None)

        by_date[current_date] = {
            # New primary metrics (response quality focused)
            'avg_response_time': float(avg_response_time) if avg_response_time > 0 else float(kpi_row.first_response_time if kpi_row else 0.0),
            'awaiting_team_reply': float(len(team_owned_tickets)),
            'open_backlog': float(len(open_tickets)) if open_tickets else float(kpi_row.open_backlog if kpi_row else 0.0),
            'engagement_depth': float(avg_engagement),

            # Keep existing metrics
            'reopen_rate': float(kpi_row.reopen_rate if kpi_row else 0.0),
            'escalation_rate': float(escalation_rate),
            'queue_concentration_pct': float(queue_concentration),

            # Header metrics (support data)
            'support_burden': float(kpi_row.tickets_per_100_orders if kpi_row else 0.0),
            'closure_sla_pct': float(max(0.0, 100.0 - (kpi_row.sla_breach_rate if kpi_row else 0.0))),
            'first_response_time': float(kpi_row.first_response_time if kpi_row else 0.0),

            # Context metrics (for insights)
            'customer_owned_tickets': float(len(open_tickets) - len(team_owned_tickets)),
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
        inverse_good = config.get('inverse_good', True)
        status = _status_for(current, config['target'], config['red'], inverse_good)

        # Build trigger condition based on metric direction
        trigger = None
        if inverse_good:
            if status == 'red':
                trigger = f'{key}_gt_{int(config["red"])}'
            elif status == 'yellow':
                trigger = f'{key}_gt_{int(config["target"])}'
        else:
            if status == 'red':
                trigger = f'{key}_lt_{int(config["red"])}'
            elif status == 'yellow':
                trigger = f'{key}_lt_{int(config["target"])}'

        # Calculate consecutive days based on metric direction
        consecutive_bad_days = 0
        consecutive_green_days = 0
        for d in reversed(ordered_dates):
            is_bad = series_by_date[d][key] > config['target'] if inverse_good else series_by_date[d][key] < config['target']
            if is_bad:
                consecutive_bad_days += 1
            else:
                break
        for d in reversed(ordered_dates):
            is_good = series_by_date[d][key] <= config['target'] if inverse_good else series_by_date[d][key] >= config['target']
            if is_good:
                consecutive_green_days += 1
            else:
                break

        recent7 = values[-7:]
        prior7 = values[-14:-7]
        recent30 = values[-30:]
        prior30 = values[-60:-30]

        # For non-inverse metrics (higher is better), flip the critical check
        is_critical = current > config['critical'] if inverse_good else current < config['critical']

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
            'critical_immediate': is_critical,
            'consecutive_bad_days': consecutive_bad_days,
            'consecutive_green_days': consecutive_green_days,
            'inverse_good': inverse_good,
            'snapshot_timestamp': datetime.combine(current_date, datetime.min.time(), tzinfo=timezone.utc),
        }

    # Header metrics focused on response quality (what really matters)
    header_metrics = [
        {
            'key': 'avg_response_time', 'label': 'Avg Response Time', 'owner': 'Jeremiah',
            'current': series_by_date[current_date]['avg_response_time'], 'target': 4.0,
            'delta': series_by_date[current_date]['avg_response_time'] - 4.0,
            'trend7d': _pct_change([series_by_date[d]['avg_response_time'] for d in ordered_dates[-7:]], [series_by_date[d]['avg_response_time'] for d in ordered_dates[-14:-7]]),
            'trend30d': _pct_change([series_by_date[d]['avg_response_time'] for d in ordered_dates[-30:]], [series_by_date[d]['avg_response_time'] for d in ordered_dates[-60:-30]]),
            'status': 'green' if series_by_date[current_date]['avg_response_time'] <= 4 else 'yellow' if series_by_date[current_date]['avg_response_time'] <= 8 else 'red',
            'confidence': 'normal', 'snapshot_timestamp': datetime.combine(current_date, datetime.min.time(), tzinfo=timezone.utc),
        },
        {
            'key': 'awaiting_team_reply', 'label': 'Awaiting Our Reply', 'owner': 'Jeremiah',
            'current': series_by_date[current_date]['awaiting_team_reply'], 'target': 30.0,
            'delta': series_by_date[current_date]['awaiting_team_reply'] - 30.0,
            'trend7d': _pct_change([series_by_date[d]['awaiting_team_reply'] for d in ordered_dates[-7:]], [series_by_date[d]['awaiting_team_reply'] for d in ordered_dates[-14:-7]]),
            'trend30d': _pct_change([series_by_date[d]['awaiting_team_reply'] for d in ordered_dates[-30:]], [series_by_date[d]['awaiting_team_reply'] for d in ordered_dates[-60:-30]]),
            'status': 'green' if series_by_date[current_date]['awaiting_team_reply'] <= 30 else 'yellow' if series_by_date[current_date]['awaiting_team_reply'] <= 50 else 'red',
            'confidence': 'normal', 'snapshot_timestamp': datetime.combine(current_date, datetime.min.time(), tzinfo=timezone.utc),
        },
        {
            'key': 'engagement_depth', 'label': 'Engagement Depth', 'owner': 'Jeremiah',
            'current': series_by_date[current_date]['engagement_depth'], 'target': 2.5,
            'delta': series_by_date[current_date]['engagement_depth'] - 2.5,
            'trend7d': _pct_change([series_by_date[d]['engagement_depth'] for d in ordered_dates[-7:]], [series_by_date[d]['engagement_depth'] for d in ordered_dates[-14:-7]]),
            'trend30d': _pct_change([series_by_date[d]['engagement_depth'] for d in ordered_dates[-30:]], [series_by_date[d]['engagement_depth'] for d in ordered_dates[-60:-30]]),
            'status': 'green' if series_by_date[current_date]['engagement_depth'] >= 2.5 else 'yellow' if series_by_date[current_date]['engagement_depth'] >= 1.5 else 'red',
            'confidence': 'normal', 'snapshot_timestamp': datetime.combine(current_date, datetime.min.time(), tzinfo=timezone.utc),
        },
        {
            'key': 'support_burden', 'label': 'Support Burden', 'owner': 'Jeremiah',
            'current': series_by_date[current_date]['support_burden'], 'target': 4.5,
            'delta': series_by_date[current_date]['support_burden'] - 4.5,
            'trend7d': _pct_change([series_by_date[d]['support_burden'] for d in ordered_dates[-7:]], [series_by_date[d]['support_burden'] for d in ordered_dates[-14:-7]]),
            'trend30d': _pct_change([series_by_date[d]['support_burden'] for d in ordered_dates[-30:]], [series_by_date[d]['support_burden'] for d in ordered_dates[-60:-30]]),
            'status': 'green' if series_by_date[current_date]['support_burden'] <= 4.5 else 'yellow' if series_by_date[current_date]['support_burden'] <= 7 else 'red',
            'confidence': 'low', 'snapshot_timestamp': datetime.combine(current_date, datetime.min.time(), tzinfo=timezone.utc),
        },
    ]

    # Build insights based on new KPI framework
    response_time = metric_map['avg_response_time']
    awaiting_reply = metric_map['awaiting_team_reply']
    engagement = metric_map['engagement_depth']
    concentration = metric_map['queue_concentration_pct']
    backlog = metric_map['open_backlog']
    reopen = metric_map['reopen_rate']
    escalation = metric_map['escalation_rate']
    top_issue = snapshot['top_issue']
    customer_owned = series_by_date[current_date].get('customer_owned_tickets', 0)

    insights: list[dict[str, Any]] = []

    # Insight: Response time health
    if response_time['status'] != 'green' and awaiting_reply['status'] != 'green':
        insights.append({
            'text': 'Customers are waiting too long for responses. Team response speed needs immediate attention.',
            'evidence': [f"Avg response time {response_time['current']:.1f}h", f"Awaiting our reply {awaiting_reply['current']:.0f}", 'Both above target'],
            'snapshot_timestamp': metric_map['open_backlog']['snapshot_timestamp'],
        })

    # Insight: Engagement quality vs reopen rate
    if engagement['status'] != 'green' and reopen['status'] != 'green':
        insights.append({
            'text': 'Low engagement depth correlates with higher reopen rate. Tickets may need more thorough initial handling.',
            'evidence': [f"Engagement depth {engagement['current']:.1f}", f"Reopen rate {reopen['current']:.1f}%", 'Deeper engagement reduces reopens'],
            'snapshot_timestamp': metric_map['open_backlog']['snapshot_timestamp'],
        })

    # Insight: Queue composition context
    if backlog['status'] != 'green':
        team_owned_pct = (awaiting_reply['current'] / backlog['current'] * 100) if backlog['current'] > 0 else 0
        if team_owned_pct < 40:
            insights.append({
                'text': f'Queue size is elevated but {100 - team_owned_pct:.0f}% of tickets are customer-owned. Focus on team-owned tickets first.',
                'evidence': [f"Total open {backlog['current']:.0f}", f"Awaiting our reply {awaiting_reply['current']:.0f}", f"Customer-owned {customer_owned:.0f}"],
                'snapshot_timestamp': metric_map['open_backlog']['snapshot_timestamp'],
            })
        elif concentration['status'] != 'green':
            insights.append({
                'text': 'Queue pressure is being driven by workload concentration, not just raw ticket volume.',
                'evidence': [f"Queue concentration {concentration['current']:.1f}%", f"Awaiting our reply {awaiting_reply['current']:.0f}", 'Rebalance assignments'],
                'snapshot_timestamp': metric_map['open_backlog']['snapshot_timestamp'],
            })

    # Insight: Escalation clustering
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
    tickets = db.execute(select(FreshdeskTicket).order_by(desc(FreshdeskTicket.updated_at_source))).scalars().all()
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
        name = str((ticket.raw_payload or {}).get('responder_name') or ticket.agent_id or 'Unassigned')
        open_by_rep[name] += 1
    for ticket in tickets:
        created = _normalize_date(ticket.created_at_source)
        if not created or created < start7 or created > snapshot_date:
            continue
        name = str((ticket.raw_payload or {}).get('responder_name') or ticket.agent_id or 'Unassigned')
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
