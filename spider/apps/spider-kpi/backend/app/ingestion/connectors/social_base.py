from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class NormalizedSignal:
    source: str
    external_id: str | None
    url: str | None
    author: str | None
    body: str
    published_at: str | None
    sentiment: str | None = None
    severity: str | None = None
    topic: str | None = None
    product: str | None = None
    confidence: float = 0.0
    metadata: dict[str, Any] | None = None


class SignalConnector(Protocol):
    source_name: str

    def configured(self) -> bool: ...

    def fetch(self) -> list[NormalizedSignal]: ...
