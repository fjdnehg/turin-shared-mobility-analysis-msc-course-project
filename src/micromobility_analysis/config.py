"""Project paths and analysis assumptions."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProjectPaths:
    """Locations of raw inputs and generated outputs."""

    data_root: Path
    results_dir: Path

    @property
    def zones_path(self) -> Path:
        return self.data_root / "Zonestatistiche_group" / "zone_statistiche_group.shp"

    @property
    def sources(self) -> dict[str, tuple[Path, str]]:
        return {
            "Lime": (self.data_root / "Operator A_Lime" / "Torino_Corse24-25.csv", ","),
            "Voi": (self.data_root / "Operator B_Voi" / "DATINOLEGGI_combined.csv", ";"),
            "Bird": (self.data_root / "Operator C_Bird" / "Bird_Torino_2024_2025_combined.csv", ","),
        }

    @property
    def figures_dir(self) -> Path:
        return self.results_dir / "figures"

    @property
    def tables_dir(self) -> Path:
        return self.results_dir / "tables"

    @property
    def maps_dir(self) -> Path:
        return self.results_dir / "maps"


TARIFFS = {
    "Lime": {"unlock_eur": 1.00, "per_min_eur": 0.28},
    "Voi": {"unlock_eur": 1.00, "per_min_eur": 0.24},
    "Bird": {"unlock_eur": 1.00, "per_min_eur": 0.29},
}

COSTS_EUR = {
    "charging_per_ride": 1.72 * 0.86,
    "repairs_per_ride": 0.51 * 0.86,
    "card_fees_per_ride": 0.41 * 0.86,
    "support_per_ride": 0.06 * 0.86,
    "insurance_per_ride": 0.05 * 0.86,
    "city_licenses_total": 3000 * 0.86,
    "designated_parking_total": 100 * 0.86,
    "annual_fee_per_scooter": 50 * 0.86,
    "daily_fee_per_scooter": 1.0 * 0.86,
    "scooter_purchase": 500 * 0.86,
    "scooter_lifespan_years": 2.5,
}
