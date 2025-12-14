"""Alert system for trading notifications."""
from __future__ import annotations


import logging
from datetime import datetime
from enum import Enum
from typing import Callable

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AlertLevel(str, Enum):
    """Alert severity levels."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class Alert(BaseModel):
    """Alert notification."""

    id: str = ""
    level: AlertLevel
    title: str
    message: str
    ticker: str = ""
    value: float = 0.0
    threshold: float = 0.0
    created_at: datetime = Field(default_factory=datetime.now)
    acknowledged: bool = False


class AlertCondition(BaseModel):
    """Condition that triggers an alert."""

    name: str
    level: AlertLevel
    check_fn_name: str
    threshold: float = 0.0
    cooldown_seconds: int = 300


class AlertManager:
    """
    Manage alerts and notifications.

    Supports:
    - Drawdown alerts
    - Correlation spike alerts
    - Large opportunity alerts
    - Execution failure alerts
    """

    def __init__(self):
        self._alerts: list[Alert] = []
        self._conditions: list[AlertCondition] = []
        self._last_triggered: dict[str, datetime] = {}
        self._handlers: list[Callable[[Alert], None]] = []

    def register_handler(self, handler: Callable[[Alert], None]) -> None:
        """Register alert handler (e.g., for notifications)."""
        self._handlers.append(handler)

    def add_condition(self, condition: AlertCondition) -> None:
        """Add an alert condition."""
        self._conditions.append(condition)

    def create_alert(
        self,
        level: AlertLevel,
        title: str,
        message: str,
        ticker: str = "",
        value: float = 0.0,
        threshold: float = 0.0,
    ) -> Alert:
        """Create and dispatch an alert."""
        alert = Alert(
            id=f"alert_{int(datetime.now().timestamp() * 1000)}",
            level=level,
            title=title,
            message=message,
            ticker=ticker,
            value=value,
            threshold=threshold,
        )

        self._alerts.append(alert)

        log_fn = {
            AlertLevel.INFO: logger.info,
            AlertLevel.WARNING: logger.warning,
            AlertLevel.CRITICAL: logger.critical,
        }.get(level, logger.info)

        log_fn(f"[{level.value.upper()}] {title}: {message}")

        for handler in self._handlers:
            try:
                handler(alert)
            except Exception as e:
                logger.error(f"Alert handler failed: {e}")

        return alert

    def check_drawdown(
        self,
        current_drawdown: float,
        warning_threshold: float = 0.10,
        critical_threshold: float = 0.20,
    ) -> Alert | None:
        """Check drawdown and create alert if needed."""
        if current_drawdown >= critical_threshold:
            return self.create_alert(
                level=AlertLevel.CRITICAL,
                title="Critical Drawdown",
                message=f"Drawdown at {current_drawdown:.1%}",
                value=current_drawdown,
                threshold=critical_threshold,
            )
        elif current_drawdown >= warning_threshold:
            return self.create_alert(
                level=AlertLevel.WARNING,
                title="Drawdown Warning",
                message=f"Drawdown at {current_drawdown:.1%}",
                value=current_drawdown,
                threshold=warning_threshold,
            )
        return None

    def check_opportunity(
        self,
        ticker: str,
        edge: float,
        min_edge: float = 0.03,
    ) -> Alert | None:
        """Alert on large opportunities."""
        if edge >= min_edge:
            return self.create_alert(
                level=AlertLevel.INFO,
                title="Large Opportunity",
                message=f"Edge of {edge:.1%} on {ticker}",
                ticker=ticker,
                value=edge,
                threshold=min_edge,
            )
        return None

    def check_execution_failure(
        self,
        ticker: str,
        reason: str,
    ) -> Alert:
        """Alert on execution failures."""
        return self.create_alert(
            level=AlertLevel.WARNING,
            title="Execution Failed",
            message=f"Failed to execute on {ticker}: {reason}",
            ticker=ticker,
        )

    def check_correlation_spike(
        self,
        cluster: str,
        correlation_change: float,
        threshold: float = 0.50,
    ) -> Alert | None:
        """Alert on correlation spikes."""
        if correlation_change >= threshold:
            return self.create_alert(
                level=AlertLevel.WARNING,
                title="Correlation Spike",
                message=f"Correlation in {cluster} increased by {correlation_change:.1%}",
                ticker=cluster,
                value=correlation_change,
                threshold=threshold,
            )
        return None

    def get_alerts(
        self,
        level: AlertLevel | None = None,
        unacknowledged_only: bool = False,
        limit: int = 100,
    ) -> list[Alert]:
        """Get alerts with optional filtering."""
        alerts = self._alerts

        if level:
            alerts = [a for a in alerts if a.level == level]

        if unacknowledged_only:
            alerts = [a for a in alerts if not a.acknowledged]

        return sorted(alerts, key=lambda a: a.created_at, reverse=True)[:limit]

    def acknowledge_alert(self, alert_id: str) -> bool:
        """Mark alert as acknowledged."""
        for alert in self._alerts:
            if alert.id == alert_id:
                alert.acknowledged = True
                return True
        return False

    def clear_old_alerts(self, max_age_hours: int = 24) -> int:
        """Remove alerts older than max_age_hours."""
        cutoff = datetime.now().timestamp() - (max_age_hours * 3600)
        old_count = len(self._alerts)
        self._alerts = [
            a for a in self._alerts if a.created_at.timestamp() > cutoff
        ]
        return old_count - len(self._alerts)
