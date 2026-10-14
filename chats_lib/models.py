"""Contrato de dados compartilhado por todos os adapters.

Todo adapter converte a sua fonte (SQLite, JSONL, JSON solto) nestes tipos.
O resto do programa nunca toca em formato de terceiro.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Registro:
    id: str
    cli: str
    title: str
    cwd: str | None = None
    created_at: int | None = None  # epoch ms
    updated_at: int | None = None  # epoch ms — ordenação principal
    preview: str = ""  # ~200 chars da 1ª mensagem do usuário
    n_msgs: int | None = None
    native_resume: list[str] = field(default_factory=list)
    source_path: str = ""
    imported_in_opencode: str | None = None
    duplicada: bool = False  # mesma conversa em ≥2 CLIs (dedupe fino)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        """Identidade estável usada na CLI, no fzf e nos atalhos."""
        return f"{self.cli}:{self.id}"

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["key"] = self.key
        return d


@dataclass
class Mensagem:
    role: str  # user | assistant | system
    text: str
    time: int | None = None
