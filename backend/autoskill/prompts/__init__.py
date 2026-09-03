"""Jinja2 prompt templates loaded from this directory."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    autoescape=False,
)


def render(name: str, **context) -> str:
    return _env.get_template(f"{name}.j2").render(**context).strip()
