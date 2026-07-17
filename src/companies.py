from __future__ import annotations

from pathlib import Path

import yaml

from .models import Company
from .settings import ROOT


def load_companies_from_yaml(path: Path | None = None) -> list[Company]:
    yaml_path = path or (ROOT / "config" / "companies.yaml")
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    companies: list[Company] = []
    for row in data.get("companies", []):
        companies.append(Company.model_validate(row))
    return companies
