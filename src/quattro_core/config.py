"""Operator-owned configuration; clients cannot register filesystem roots."""
from __future__ import annotations

import json
import math
import os
import pathlib
import re
import tempfile
from dataclasses import dataclass
from typing import Any

NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")


def identifier(value: Any) -> str:
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise ValueError("invalid namespace or identity")
    return value


def safe_path(value: Any, *, directory: bool = False) -> pathlib.Path:
    if not isinstance(value, (str, pathlib.Path)):
        raise ValueError("path must be absolute")
    path = pathlib.Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("path must be absolute without traversal")
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("symbolic-link paths are not authorized")
    if directory and not path.is_dir():
        raise ValueError("source directory is unavailable")
    return path


@dataclass(frozen=True)
class Source:
    id: str
    project: str
    root: pathlib.Path
    kind: str = "repository"
    exclusions: tuple[str, ...] = ()
    authority: float = 0.8
    intent: str = "undecided"
    exclusion_reason: str | None = None

    def __post_init__(self) -> None:
        identifier(self.id)
        identifier(self.project)
        safe_path(self.root)
        if self.kind not in {"repository", "documentation", "obsidian"}:
            raise ValueError("unsupported source kind")
        if (not isinstance(self.exclusions, tuple) or len(self.exclusions) > 100
                or any(not isinstance(p, str) or not p or len(p) > 200 for p in self.exclusions)):
            raise ValueError("invalid source exclusions")
        if type(self.authority) not in {int, float} or not math.isfinite(self.authority) or not 0 <= self.authority <= 1:
            raise ValueError("invalid source authority")
        if self.intent not in {"intended", "undecided", "excluded"}:
            raise ValueError("invalid source intent")
        if self.exclusion_reason is not None and (not isinstance(self.exclusion_reason, str) or
                not self.exclusion_reason.strip() or len(self.exclusion_reason) > 200):
            raise ValueError("invalid source exclusion reason")
        if self.intent == "excluded" and not self.exclusion_reason:
            raise ValueError("excluded sources require a reason")


@dataclass(frozen=True)
class Config:
    database_dir: pathlib.Path
    sources: tuple[Source, ...]
    projects: tuple[str, ...]
    principal: str = "local"
    writable: bool = False
    can_verify: bool = False
    embedding: str = "lexical"
    rrf_k: int = 60
    lexical_weight: float = 1.0
    semantic_weight: float = 1.0

    def __post_init__(self) -> None:
        safe_path(self.database_dir)
        identifier(self.principal)
        if not self.projects or len(set(self.projects)) != len(self.projects):
            raise ValueError("projects must be nonempty and unique")
        for project in self.projects:
            identifier(project)
        if len({s.id for s in self.sources}) != len(self.sources):
            raise ValueError("source IDs must be unique")
        if any(s.project not in self.projects for s in self.sources):
            raise ValueError("source namespace is not authorized")
        if type(self.writable) is not bool or type(self.can_verify) is not bool:
            raise ValueError("access flags must be booleans")
        if self.embedding not in {"lexical", "local-neural"}:
            raise ValueError("unsupported embedding backend")
        if type(self.rrf_k) is not int or not 1 <= self.rrf_k <= 1000:
            raise ValueError("invalid rank-fusion constant")
        for weight in (self.lexical_weight, self.semantic_weight):
            if type(weight) not in {int, float} or not math.isfinite(weight) or not 0 <= weight <= 10:
                raise ValueError("invalid rank-fusion weight")
        if not self.lexical_weight and not self.semantic_weight:
            raise ValueError("rank fusion requires a nonzero weight")

    def authorize(self, project: str, write: bool = False) -> None:
        if project not in self.projects:
            raise PermissionError("project is not authorized")
        if write and not self.writable:
            raise PermissionError("write access is disabled")

    def source(self, source_id: str) -> Source:
        for source in self.sources:
            if source.id == source_id:
                self.authorize(source.project)
                return source
        raise PermissionError("source is not authorized")

    @classmethod
    def load(cls, path: pathlib.Path) -> "Config":
        path = safe_path(path)
        if not path.is_file() or path.stat().st_size > 128_000:
            raise ValueError("intelligence configuration is unavailable or oversized")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("invalid intelligence configuration") from error
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        fields = {"version", "database_dir", "sources", "projects", "principal", "writable", "can_verify", "embedding", "fusion"}
        if not isinstance(data, dict) or set(data) - fields or data.get("version") != 1:
            raise ValueError("unsupported intelligence configuration")
        if not isinstance(data.get("projects"), list) or not isinstance(data.get("sources", []), list):
            raise ValueError("projects and sources must be arrays")
        sources = []
        for raw in data.get("sources", []):
            if not isinstance(raw, dict) or set(raw) - {"id", "project", "root", "kind", "exclusions", "authority", "intent", "exclusion_reason"}:
                raise ValueError("invalid source configuration")
            exclusions = raw.get("exclusions", [])
            if not isinstance(exclusions, list):
                raise ValueError("exclusions must be an array")
            sources.append(Source(identifier(raw.get("id")), identifier(raw.get("project")),
                                  safe_path(raw.get("root")), raw.get("kind", "repository"),
                                  tuple(exclusions), raw.get("authority", 0.8),
                                  raw.get("intent", "undecided"), raw.get("exclusion_reason")))
        fusion = data.get("fusion", {})
        if not isinstance(fusion, dict) or set(fusion) - {"rrf_k", "lexical_weight", "semantic_weight"}:
            raise ValueError("invalid fusion configuration")
        return cls(safe_path(data.get("database_dir")), tuple(sources), tuple(data["projects"]),
                   data.get("principal", "local"), data.get("writable", False), data.get("can_verify", False),
                   data.get("embedding", "lexical"), **fusion)

    def projection(self) -> dict[str, Any]:
        return {"version": 1, "database_dir": str(self.database_dir), "projects": list(self.projects),
                "principal": self.principal, "writable": self.writable, "can_verify": self.can_verify,
                "embedding": self.embedding,
                "fusion": {"rrf_k": self.rrf_k, "lexical_weight": self.lexical_weight, "semantic_weight": self.semantic_weight},
                "sources": [{"id": s.id, "project": s.project, "root": str(s.root), "kind": s.kind,
                             "exclusions": list(s.exclusions), "authority": s.authority,
                             "intent": s.intent, "exclusion_reason": s.exclusion_reason} for s in self.sources]}

    def save(self, path: pathlib.Path) -> None:
        path = safe_path(path)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".intelligence-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(self.projection(), stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def default_config_path() -> pathlib.Path:
    return pathlib.Path.home() / ".config/quattro/intelligence.json"


def register_source(path: pathlib.Path, source: Source) -> Config:
    config = Config.load(path)
    config.authorize(source.project, write=True)
    if any(s.id == source.id for s in config.sources):
        raise ValueError("source ID already registered")
    updated = Config.from_dict({**config.projection(), "sources": [*config.projection()["sources"],
        {"id": source.id, "project": source.project, "root": str(source.root), "kind": source.kind,
         "exclusions": list(source.exclusions), "authority": source.authority,
         "intent":source.intent, "exclusion_reason":source.exclusion_reason}]})
    updated.save(path)
    return updated
