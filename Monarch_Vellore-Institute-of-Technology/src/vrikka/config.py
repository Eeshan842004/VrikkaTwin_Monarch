"""Configuration loader for VrikkaTwin (master plan §8, §18).

All model constants come from ``config/parameters.yaml`` (the Parameter Provenance Registry). Code calls
``param("d50")`` instead of typing a number, so every constant has a unit, a range, a provenance label and a
source. Other YAML files (cohort, cities, alert policy, lexicons) are loaded with ``load_yaml``.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = PROJECT_ROOT / "reports"
MODELS_DIR = PROJECT_ROOT / "models"

SEED = 42


class Parameter(BaseModel):
    """One registry entry."""

    value: float | int
    unit: str
    range: tuple[float, float]
    provenance: Literal["CITED", "VERIFY", "ASSUMPTION"]
    source: str
    notes: str = ""

    @model_validator(mode="after")
    def _range_is_ordered(self) -> Parameter:
        lo, hi = self.range
        if lo > hi:
            raise ValueError(f"range low {lo} > high {hi}")
        return self


class Settings(BaseSettings):
    """Runtime settings from the environment / .env (see .env.example)."""

    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    app_mode: Literal["api", "inprocess"] = "inprocess"
    secret_key: str = Field(default="dev-only-jwt-secret-change-me-before-any-deployment")
    fernet_key: str = ""
    audit_key: str = "dev-only-key"
    openmeteo_base: str = "https://archive-api.open-meteo.com/v1/archive"
    whisper_model: str = "small"
    api_url: str = "http://127.0.0.1:8000"
    # demo logins (role: password); demo only, never reuse (see .env.example)
    demo_doctor_password: str = "doctor-demo"
    demo_patient_password: str = "patient-demo"
    demo_family_password: str = "family-demo"
    demo_asha_password: str = "asha-demo"
    demo_lab_password: str = "lab-demo"
    demo_admin_password: str = "admin-demo"


def load_yaml(name: str) -> Any:
    """Load a YAML file from config/ (name with or without the .yaml suffix)."""
    path = CONFIG_DIR / (name if name.endswith((".yaml", ".yml")) else f"{name}.yaml")
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@lru_cache(maxsize=1)
def registry() -> dict[str, Parameter]:
    """The full Parameter Provenance Registry, validated."""
    raw = load_yaml("parameters")
    return {name: Parameter(**entry) for name, entry in raw.items()}


def param(name: str) -> float:
    """Value of one registry parameter. Raises KeyError for unknown names (never guess a number)."""
    return registry()[name].value


def param_range(name: str) -> tuple[float, float]:
    """Sensitivity range of one registry parameter (used by the tornado analysis)."""
    return registry()[name].range


@contextmanager
def overrides(**values: float) -> Iterator[None]:
    """Temporarily replace registry values (sensitivity analysis and tests only; never used by the product path).

    Values must stay inside each parameter's registered range, so a sensitivity run cannot use numbers the registry
    does not allow.
    """
    reg = registry()
    old = {k: reg[k] for k in values}
    try:
        for k, v in values.items():
            lo, hi = reg[k].range
            if not lo - 1e-12 <= v <= hi + 1e-12:
                raise ValueError(f"{k}={v} is outside its registered range {reg[k].range}")
            reg[k] = reg[k].model_copy(update={"value": v})
        yield
    finally:
        reg.update(old)


@lru_cache(maxsize=1)
def settings() -> Settings:
    return Settings()
