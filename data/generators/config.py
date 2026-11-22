"""Parâmetros do gerador. Tudo que muda o conteúdo entra no hash (idempotência)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta

GENERATOR_VERSION = 1


@dataclass(frozen=True)
class GenConfig:
    seed: int = 42
    end_date: date = date(2026, 10, 31)
    n_customers: int = 5000
    n_products: int = 500
    n_categories: int = 20
    n_orders: int = 20000
    months: int = 24
    dq_lab_orders: int = 400  # pedidos válidos copiados para a linha de base do dq_lab

    @property
    def start_date(self) -> date:
        """Primeiro dia do mês, `months` meses antes do mês de end_date (inclusive)."""
        y, m = self.end_date.year, self.end_date.month
        total = y * 12 + (m - 1) - (self.months - 1)
        return date(total // 12, total % 12 + 1, 1)

    def params_hash(self) -> str:
        payload = {k: str(v) for k, v in asdict(self).items()}
        payload["generator_version"] = GENERATOR_VERSION
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]

    def days(self) -> list[date]:
        n = (self.end_date - self.start_date).days + 1
        return [self.start_date + timedelta(days=i) for i in range(n)]
