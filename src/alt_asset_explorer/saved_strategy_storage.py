"""Storage boundary dedicated to versioned saved portfolio/strategy documents."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import ValidationError

from alt_asset_explorer.saved_strategies import SavedStrategyDefinition


class SavedStrategyStorageError(RuntimeError):
    pass


class DuplicateSavedStrategyError(SavedStrategyStorageError):
    pass


class SavedStrategyStorage(ABC):
    @abstractmethod
    def list(self) -> list[SavedStrategyDefinition]: ...

    @abstractmethod
    def get(self, strategy_id: str) -> SavedStrategyDefinition | None: ...

    @abstractmethod
    def save(self, definition: SavedStrategyDefinition) -> SavedStrategyDefinition: ...


class JsonDirectorySavedStrategyStorage(SavedStrategyStorage):
    """Atomic local JSON adapter; callers must use a non-custom-index directory."""

    def __init__(self, directory: Path, *, read_only: bool = False):
        self.directory = Path(directory)
        self.read_only = read_only
        if self.directory.name == "custom_indices" or "custom_indices" in self.directory.parts:
            raise ValueError("saved strategies must not be stored in the custom-index directory")

    def _load_path(self, path: Path) -> SavedStrategyDefinition | None:
        try:
            return SavedStrategyDefinition.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, ValidationError, json.JSONDecodeError):
            return None

    def list(self) -> list[SavedStrategyDefinition]:
        if not self.directory.exists():
            return []
        records = [record for path in sorted(self.directory.glob("*.json")) if (record := self._load_path(path))]
        return sorted(records, key=lambda item: item.updated_at, reverse=True)

    def get(self, strategy_id: str) -> SavedStrategyDefinition | None:
        path = self.directory / f"{strategy_id}.json"
        return self._load_path(path) if path.exists() else None

    def save(self, definition: SavedStrategyDefinition) -> SavedStrategyDefinition:
        if self.read_only:
            raise SavedStrategyStorageError("This saved-strategy store is read-only.")
        definition = SavedStrategyDefinition.model_validate(definition)
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.get(definition.id):
            raise DuplicateSavedStrategyError(f"A strategy with ID {definition.id!r} already exists.")
        if any(item.name.casefold() == definition.name.casefold() for item in self.list()):
            raise DuplicateSavedStrategyError(f"A strategy named {definition.name!r} already exists.")
        destination = self.directory / f"{definition.id}.json"
        temporary = destination.with_suffix(".tmp")
        try:
            temporary.write_text(definition.model_dump_json(indent=2), encoding="utf-8")
            temporary.replace(destination)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise SavedStrategyStorageError(f"Unable to save strategy: {exc}") from exc
        return definition
