"""Resolve consist length from the exact TPF2 model resources used by a vehicle."""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any


VECTOR = re.compile(r"\b(bbMax|bbMin)\s*=\s*\{\s*([-+0-9.eE]+)\s*,\s*([-+0-9.eE]+)\s*,\s*([-+0-9.eE]+)", re.I)


class VehicleModelLengthResolver:
    def __init__(self, game_directory: Path):
        self.game_directory = Path(game_directory)
        self.model_roots = [self.game_directory / "res" / "models" / "model"]
        self.base_model_archive = self.game_directory / "res" / "models" / "model.zip"
        mods = self.game_directory / "mods"
        if mods.is_dir():
            self.model_roots.extend(path / "res" / "models" / "model" for path in mods.iterdir() if path.is_dir())
        workshop = self.game_directory.parent.parent / "workshop" / "content" / "1066780"
        if workshop.is_dir():
            self.model_roots.extend(path / "res" / "models" / "model" for path in workshop.iterdir() if path.is_dir())
        self._cache: dict[str, tuple[float | None, str | None]] = {}

    def model_length(self, model_name: str) -> tuple[float | None, str | None]:
        normalized = str(model_name).replace("\\", "/")
        if normalized in self._cache:
            return self._cache[normalized]
        relative = Path(*normalized.replace("\\", "/").split("/"))
        if self.base_model_archive.is_file():
            member = "model/" + normalized
            try:
                with zipfile.ZipFile(self.base_model_archive) as archive:
                    head = archive.read(member)[:16384].decode("utf-8", errors="ignore")
                resolved = self._length_from_source(head)
                if resolved is not None:
                    self._cache[normalized] = (resolved, f"{self.base_model_archive}!/{member}")
                    return self._cache[normalized]
            except (KeyError, OSError, zipfile.BadZipFile):
                pass
        for root in self.model_roots:
            path = root / relative
            if not path.is_file():
                continue
            try:
                head = path.read_text(encoding="utf-8", errors="ignore")[:16384]
            except OSError:
                continue
            length = self._length_from_source(head)
            if length is not None:
                self._cache[normalized] = (length, str(path))
                return self._cache[normalized]
        self._cache[normalized] = (None, None)
        return self._cache[normalized]

    @staticmethod
    def _length_from_source(source: str) -> float | None:
        values = {match.group(1).lower(): tuple(float(match.group(index)) for index in (2, 3, 4)) for match in VECTOR.finditer(source)}
        length = values["bbmax"][0] - values["bbmin"][0] if "bbmax" in values and "bbmin" in values else None
        return length if isinstance(length, float) and length > 0 else None

    def enrich_snapshot(self, snapshot: dict[str, Any], coupling_margin_m: float = 1.0) -> dict[str, int]:
        known = missing = 0
        for vehicle in snapshot.get("vehicles", []):
            parts = vehicle.get("consist_parts", [])
            lengths, sources = [], []
            for part in parts:
                length, source = self.model_length(part.get("model_name", ""))
                part["model_length_m"] = round(length, 3) if length is not None else None
                part["model_length_source"] = source
                if length is not None:
                    lengths.append(length); sources.append(source)
            if parts and len(lengths) == len(parts):
                vehicle["consist_length_m"] = round(sum(lengths) + max(0, len(parts) - 1) * coupling_margin_m, 3)
                vehicle["consist_length_source"] = "MODEL_BOUNDING_INFO_X_SUM_PLUS_COUPLING_MARGIN"
                vehicle["consist_length_coupling_margin_m"] = coupling_margin_m
                vehicle["consist_length_confidence"] = "MEDIUM_CONSERVATIVE"
                known += 1
            else:
                missing += 1
        return {"known_vehicle_lengths": known, "missing_vehicle_lengths": missing, "resolved_model_count": sum(value[0] is not None for value in self._cache.values())}
