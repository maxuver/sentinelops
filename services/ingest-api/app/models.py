"""Pydantic models for the Alertmanager webhook payload (version 4).

Reference: https://prometheus.io/docs/alerting/latest/configuration/#webhook_config
"""

from datetime import datetime

from pydantic import BaseModel, Field


class Alert(BaseModel):
    status: str
    labels: dict[str, str]
    annotations: dict[str, str] = Field(default_factory=dict)
    startsAt: datetime | None = None
    endsAt: datetime | None = None
    generatorURL: str = ""
    fingerprint: str = ""


class AlertmanagerWebhook(BaseModel):
    version: str = "4"
    groupKey: str = ""
    status: str
    receiver: str = ""
    groupLabels: dict[str, str] = Field(default_factory=dict)
    commonLabels: dict[str, str] = Field(default_factory=dict)
    commonAnnotations: dict[str, str] = Field(default_factory=dict)
    externalURL: str = ""
    alerts: list[Alert]
