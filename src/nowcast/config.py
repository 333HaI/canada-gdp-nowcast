"""Load and validate config/series.yaml."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "series.yaml"

SOURCES = {"statcan", "boc", "fred", "manual"}
FREQS = {"M", "Q"}
TRANSFORMS = {"dlog", "diff", "level"}


@dataclass(frozen=True)
class Series:
    key: str
    name: str
    source: str
    ids: tuple  # one id, or several to splice (oldest first)
    freq: str
    transform: str
    blocks: tuple
    release_lag: int
    native_freq: str | None = None
    table: str | None = None


@dataclass(frozen=True)
class Config:
    series: tuple[Series, ...]
    start: str
    target: str
    mask: tuple = field(default_factory=tuple)

    def get(self, key: str) -> Series:
        for s in self.series:
            if s.key == key:
                return s
        raise KeyError(key)

    def by_source(self, source: str) -> list[Series]:
        return [s for s in self.series if s.source == source]

    @property
    def monthly(self) -> list[Series]:
        return [s for s in self.series if s.freq == "M"]

    @property
    def quarterly(self) -> list[Series]:
        return [s for s in self.series if s.freq == "Q"]


def load_config(path: str | Path = DEFAULT_CONFIG) -> Config:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    settings = raw.get("settings", {})
    series = []
    for item in raw["series"]:
        ids = item["id"] if isinstance(item["id"], list) else [item["id"]]
        series.append(
            Series(
                key=item["key"],
                name=item["name"],
                source=item["source"],
                ids=tuple(str(i) for i in ids),
                freq=item["freq"],
                transform=item["transform"],
                blocks=tuple(item.get("blocks", ["global"])),
                release_lag=int(item.get("release_lag", 0)),
                native_freq=item.get("native_freq"),
                table=item.get("table"),
            )
        )
    cfg = Config(
        series=tuple(series),
        start=str(settings.get("start", "1997-01-01")),
        target=settings["target"],
        mask=tuple(tuple(w) for w in settings.get("mask") or []),
    )
    validate(cfg)
    return cfg


def validate(cfg: Config) -> None:
    keys = [s.key for s in cfg.series]
    dupes = {k for k in keys if keys.count(k) > 1}
    if dupes:
        raise ValueError(f"duplicate series keys: {sorted(dupes)}")
    for s in cfg.series:
        if s.source not in SOURCES:
            raise ValueError(f"{s.key}: unknown source {s.source!r}")
        if s.freq not in FREQS:
            raise ValueError(f"{s.key}: unknown freq {s.freq!r}")
        if s.transform not in TRANSFORMS:
            raise ValueError(f"{s.key}: unknown transform {s.transform!r}")
        if "global" not in s.blocks:
            raise ValueError(f"{s.key}: every series must load on the global block")
        if s.source == "manual" and len(s.ids) != 1:
            raise ValueError(f"{s.key}: manual series take a single CSV path")
    target = cfg.get(cfg.target)
    if target.freq != "Q":
        raise ValueError("target must be a quarterly series")
