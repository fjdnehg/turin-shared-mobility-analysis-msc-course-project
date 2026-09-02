"""End-to-end, reproducible analysis workflow for Turin shared micromobility."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import folium
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from branca.colormap import LinearColormap
from folium.plugins import HeatMap
from shapely.geometry import LineString

from .config import COSTS_EUR, ProjectPaths, TARIFFS


STANDARD_COLUMNS = [
    "trip_id", "vehicle_id", "start_time", "end_time", "start_lat", "start_lon",
    "end_lat", "end_lon", "distance_km", "duration_min", "operator", "vehicle_type",
]

COLUMN_MAPPINGS = {
    "Lime": {
        "ID_VEICOLO": "vehicle_id", "DATAORA_INIZIO": "start_time",
        "DATAORA_FINE": "end_time", "LATITUDINE_INIZIO_CORSA": "start_lat",
        "LONGITUTIDE_INIZIO_CORSA": "start_lon", "LATITUDINE_FINE_CORSA": "end_lat",
        "LONGITUTIDE_FINE_CORSA": "end_lon", "DISTANZA_KM": "distance_km",
        "DURATA_MIN": "duration_min",
    },
    "Voi": {
        "Identificativo noleggio": "trip_id", "Targa veicolo": "vehicle_id",
        "Data inizio corsa": "start_time", "Data fine corsa": "end_time",
        "Lat inizio corsa_coordinate": "start_lat", "Lon inizio corsa_coordinate": "start_lon",
        "Lat fine corsa_coordinate": "end_lat", "Lon fine corsa_coordinate": "end_lon",
        "KM Tot": "distance_km", "Tempo Tot": "duration_min",
    },
    "Bird": {
        "ID_VEICOLO": "vehicle_id", "DATAORA_INIZIO": "start_time",
        "DATAORA_FINE": "end_time", "LATITUDINE_INIZIO_CORSA": "start_lat",
        "LONGITUTIDE_INIZIO_CORSA": "start_lon", "LATITUDINE_FINE_CORSA": "end_lat",
        "LONGITUTIDE_FINE_CORSA": "end_lon", "DISTANZA_KM": "distance_km",
        "DURATA_MIN": "duration_min",
    },
}


def ensure_output_dirs(paths: ProjectPaths) -> None:
    for directory in (paths.figures_dir, paths.tables_dir, paths.maps_dir):
        directory.mkdir(parents=True, exist_ok=True)


def standardize(raw: pd.DataFrame, operator: str) -> pd.DataFrame:
    """Map one operator's schema to the common trip schema."""
    out = raw.rename(columns=COLUMN_MAPPINGS[operator]).copy()
    out["operator"] = operator
    out["vehicle_type"] = "e-scooter"
    if "trip_id" not in out:
        out["trip_id"] = operator + "_" + out.index.astype(str)
    for column in STANDARD_COLUMNS:
        if column not in out:
            out[column] = pd.NA
    return out[STANDARD_COLUMNS]


def parse_datetime(values: pd.Series, operator: str) -> pd.Series:
    """Parse source-specific timestamps while coercing malformed values to NaT."""
    text = values.astype("string").str.strip()
    if operator == "Voi":
        digits = text.str.replace(r"\D", "", regex=True)
        return pd.to_datetime(digits.where(digits.str.len() == 14), format="%Y%m%d%H%M%S", errors="coerce")
    if operator == "Bird":
        text = text.str.replace(",", "", regex=False)
    return pd.to_datetime(text, errors="coerce")


def normalize_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce numbers from heterogeneous CSV formatting, including decimal commas."""
    out = df.copy()
    for column in ["distance_km", "duration_min", "start_lat", "start_lon", "end_lat", "end_lon"]:
        values = out[column].astype("string").str.strip().str.replace(",", ".", regex=False)
        out[column] = pd.to_numeric(values, errors="coerce")
    return out


def load_trips(paths: ProjectPaths) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for operator, (csv_path, separator) in paths.sources.items():
        if not csv_path.exists():
            raise FileNotFoundError(f"Missing input for {operator}: {csv_path}")
        raw = pd.read_csv(csv_path, sep=separator, on_bad_lines="warn")
        frames.append(standardize(raw, operator))

    trips = normalize_numeric(pd.concat(frames, ignore_index=True))
    for operator in paths.sources:
        mask = trips["operator"].eq(operator)
        trips.loc[mask, "start_time"] = parse_datetime(trips.loc[mask, "start_time"], operator)
        trips.loc[mask, "end_time"] = parse_datetime(trips.loc[mask, "end_time"], operator)
    return trips


def clean_trips(trips: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply transparent trip-quality rules and return the quality report."""
    report = {"input_rows": len(trips)}
    clean = trips.dropna(subset=["start_time", "end_time", "start_lat", "start_lon", "end_lat", "end_lon"]).copy()
    report["dropped_missing_required_fields"] = len(trips) - len(clean)

    valid_time = clean["end_time"] >= clean["start_time"]
    report["dropped_end_before_start"] = int((~valid_time).sum())
    clean = clean.loc[valid_time].copy()

    before_deduplication = len(clean)
    clean = clean.drop_duplicates(subset=["operator", "trip_id"]).copy()
    report["dropped_duplicate_trip_ids"] = before_deduplication - len(clean)
    report["final_rows"] = len(clean)

    quality = pd.DataFrame([report])
    return clean, quality


def add_time_fields(trips: pd.DataFrame) -> pd.DataFrame:
    out = trips.copy()
    out["year"] = out["start_time"].dt.year
    out["month_num"] = out["start_time"].dt.month
    iso = out["start_time"].dt.isocalendar()
    out["iso_year"] = iso.year.astype(int)
    out["iso_week"] = iso.week.astype(int)
    out["hour"] = out["start_time"].dt.hour
    out["period"] = np.select(
        [out["hour"].between(6, 10), out["hour"].between(12, 14), out["hour"].between(16, 20)],
        ["morning_peak", "lunch_peak", "evening_peak"],
        default="off_peak",
    )
    return out


def save_temporal_figures(trips: pd.DataFrame, paths: ProjectPaths) -> None:
    monthly = trips.groupby(["year", "month_num", "operator"]).size().reset_index(name="trips")
    yearly = trips.groupby(["year", "operator"]).size().reset_index(name="trips")
    weekly = trips.groupby(["iso_year", "iso_week", "operator"]).size().reset_index(name="trips")

    for year in sorted(weekly["iso_year"].unique()):
        pivot = weekly[weekly["iso_year"].eq(year)].pivot(index="iso_week", columns="operator", values="trips").sort_index()
        ax = pivot.plot(figsize=(12, 5))
        ticks = list(pivot.index[::4])
        ax.set_xticks(ticks, [f"{week:02d} - {date.fromisocalendar(int(year), int(week), 1):%b}" for week in ticks], rotation=45)
        ax.set(title=f"Weekly mobility trends ({year})", xlabel="ISO week", ylabel="Trips")
        ax.figure.tight_layout()
        ax.figure.savefig(paths.figures_dir / f"weekly_mobility_trends_{year}.png", dpi=300)
        plt.close(ax.figure)

    for year in sorted(monthly["year"].unique()):
        pivot = monthly[monthly["year"].eq(year)].pivot(index="month_num", columns="operator", values="trips").reindex(range(1, 13))
        ax = pivot.plot(marker="o", figsize=(12, 5))
        ax.set_xticks(range(1, 13), [date(int(year), month, 1).strftime("%b") for month in range(1, 13)])
        ax.set(title=f"Monthly mobility trends ({year})", xlabel="Month", ylabel="Trips")
        ax.figure.tight_layout()
        ax.figure.savefig(paths.figures_dir / f"monthly_mobility_trends_{year}.png", dpi=300)
        plt.close(ax.figure)

    ax = yearly.pivot(index="year", columns="operator", values="trips").plot(kind="bar", figsize=(8, 4))
    ax.set(title="Yearly mobility trends", xlabel="Year", ylabel="Trips")
    ax.figure.tight_layout()
    ax.figure.savefig(paths.figures_dir / "yearly_mobility_trends.png", dpi=300)
    plt.close(ax.figure)


def load_zones(paths: ProjectPaths) -> gpd.GeoDataFrame:
    if not paths.zones_path.exists():
        raise FileNotFoundError(f"Missing zone shapefile: {paths.zones_path}")
    zones = gpd.read_file(paths.zones_path).to_crs("EPSG:4326")
    zones = zones[["ZONASTAT", "DENOM", "geometry"]].rename(columns={"ZONASTAT": "zone_id", "DENOM": "zone_name"})
    zones["zone_id"] = zones["zone_id"].astype("string").str.strip().str.zfill(2)
    return zones


def assign_zones(trips: pd.DataFrame, zones: gpd.GeoDataFrame, lat: str, lon: str, output: str) -> pd.DataFrame:
    """Assign each trip coordinate to one statistical zone, retaining unmatched rows."""
    points = trips[["row_id", lat, lon]].copy()
    points = gpd.GeoDataFrame(points, geometry=gpd.points_from_xy(points[lon], points[lat]), crs="EPSG:4326")
    joined = gpd.sjoin(points, zones[["zone_id", "geometry"]], how="left", predicate="within")
    joined = joined.drop_duplicates(subset="row_id").set_index("row_id")["zone_id"].rename(output)
    return trips["row_id"].map(joined)


def build_od(trips: pd.DataFrame, zones: gpd.GeoDataFrame) -> pd.DataFrame:
    out = trips.reset_index(drop=True).copy()
    out["row_id"] = out.index
    out["origin_zone"] = assign_zones(out, zones, "start_lat", "start_lon", "origin_zone")
    out["destination_zone"] = assign_zones(out, zones, "end_lat", "end_lon", "destination_zone")
    return out


def save_od_outputs(od_trips: pd.DataFrame, zones: gpd.GeoDataFrame, paths: ProjectPaths) -> None:
    zone_names = zones.set_index("zone_id")["zone_name"]
    valid = od_trips.dropna(subset=["origin_zone", "destination_zone"]).copy()
    table = valid.groupby(["origin_zone", "destination_zone"]).size().reset_index(name="trips")
    table["origin_name"] = table["origin_zone"].map(zone_names)
    table["destination_name"] = table["destination_zone"].map(zone_names)
    table.sort_values("trips", ascending=False).to_csv(paths.tables_dir / "od_table_all.csv", index=False)

    period_table = valid.groupby(["period", "origin_zone", "destination_zone"]).size().reset_index(name="trips")
    period_table["origin_name"] = period_table["origin_zone"].map(zone_names)
    period_table["destination_name"] = period_table["destination_zone"].map(zone_names)
    period_table.sort_values(["period", "trips"], ascending=[True, False]).to_csv(paths.tables_dir / "od_table_by_period.csv", index=False)

    projected = zones.to_crs("EPSG:32632").copy()
    projected["geometry"] = projected.geometry.centroid
    centroid_map = projected.to_crs("EPSG:4326").set_index("zone_id").geometry.to_dict()
    def top_flows(data: pd.DataFrame) -> gpd.GeoDataFrame:
        flows = data[data["origin_zone"].ne(data["destination_zone"])].copy()
        if flows.empty:
            return gpd.GeoDataFrame(flows, geometry=[], crs="EPSG:4326")
        flows = flows[flows["trips"] >= flows["trips"].quantile(0.95)].copy()
        flows["geometry"] = [LineString([centroid_map[o], centroid_map[d]]) for o, d in zip(flows["origin_zone"], flows["destination_zone"])]
        return gpd.GeoDataFrame(flows, geometry="geometry", crs="EPSG:4326")

    def plot_flows(flows: gpd.GeoDataFrame, title: str, output: Path) -> None:
        if flows.empty:
            return
        fig, ax = plt.subplots(figsize=(10, 10))
        zones.plot(ax=ax, color="white", edgecolor="lightgrey")
        flows.plot(ax=ax, linewidth=flows["trips"] / flows["trips"].max() * 5, color="#1565c0", alpha=0.7)
        ax.set_title(title)
        ax.axis("off")
        fig.tight_layout()
        fig.savefig(output, dpi=300)
        plt.close(fig)

    flows = top_flows(table)
    if not flows.empty:
        flows.to_file(paths.results_dir / "top_od_flows.geojson", driver="GeoJSON")
        plot_flows(flows, "Top origin-destination flows", paths.figures_dir / "od_flows_all.png")
    for period in ("morning_peak", "lunch_peak", "evening_peak", "off_peak"):
        period_flows = top_flows(period_table[period_table["period"].eq(period)])
        plot_flows(period_flows, f"Top OD flows - {period.replace('_', ' ')}", paths.figures_dir / f"od_flows_{period}.png")


def make_heatmap(df: pd.DataFrame, lat: str, lon: str, output: Path) -> None:
    coordinates = df[[lat, lon]].dropna()
    if coordinates.empty:
        return
    map_obj = folium.Map(location=[coordinates[lat].median(), coordinates[lon].median()], zoom_start=12, tiles="cartodbpositron")
    HeatMap(coordinates.values.tolist(), radius=10, blur=15, max_zoom=13).add_to(map_obj)
    map_obj.save(output)


def save_heatmaps(od_trips: pd.DataFrame, paths: ProjectPaths) -> None:
    for period in ("morning_peak", "lunch_peak", "evening_peak", "off_peak"):
        subset = od_trips[od_trips["period"].eq(period)]
        make_heatmap(subset, "start_lat", "start_lon", paths.maps_dir / f"heatmap_origins_{period}.html")
        make_heatmap(subset, "end_lat", "end_lon", paths.maps_dir / f"heatmap_destinations_{period}.html")


def calculate_parking(trips: pd.DataFrame, zones: gpd.GeoDataFrame) -> pd.DataFrame:
    """Calculate inter-trip parking intervals per operator and vehicle."""
    parking = trips.sort_values(["operator", "vehicle_id", "start_time"]).copy()
    parking["next_start_time"] = parking.groupby(["operator", "vehicle_id"])["start_time"].shift(-1)
    parking["parking_min"] = (parking["next_start_time"] - parking["end_time"]).dt.total_seconds() / 60
    parking = parking[parking["parking_min"].between(0, 24 * 60)].copy()
    parking["end_hour"] = parking["end_time"].dt.hour
    parking = parking.reset_index(drop=True)
    parking["row_id"] = parking.index
    parking["end_zone"] = assign_zones(parking, zones, "end_lat", "end_lon", "end_zone")
    return parking


def add_parking_layer(map_obj: folium.Map, zones: gpd.GeoDataFrame, title: str) -> None:
    values = zones["avg_parking_min"].dropna()
    vmin, vmax = (values.min(), values.max()) if not values.empty else (0, 1)
    if vmin == vmax:
        vmax = vmin + 1e-9
    ramp = LinearColormap(["#1a9850", "#91cf60", "#fee08b", "#fc8d59", "#d73027"], vmin=vmin, vmax=vmax, caption=title)

    def style(feature: dict) -> dict:
        value = feature["properties"].get("avg_parking_min")
        return {"fillColor": ramp(value) if value is not None else "#d9d9d9", "color": "#4d4d4d", "weight": 0.8, "fillOpacity": 0.7}

    folium.GeoJson(zones, style_function=style, tooltip=folium.GeoJsonTooltip(
        fields=["zone_name", "avg_parking_min", "n_events"], aliases=["Zone", "Avg parking (min)", "N events"], localize=True
    )).add_to(map_obj)
    ramp.add_to(map_obj)


def save_parking_outputs(parking: pd.DataFrame, zones: gpd.GeoDataFrame, paths: ProjectPaths) -> None:
    grouped = parking.dropna(subset="end_zone").groupby("end_zone").agg(avg_parking_min=("parking_min", "mean"), n_events=("parking_min", "size")).reset_index()
    by_operator = parking.dropna(subset="end_zone").groupby(["operator", "end_zone"], as_index=False).agg(avg_parking_min=("parking_min", "mean"), n_events=("parking_min", "size"))
    by_operator.to_csv(paths.tables_dir / "avg_parking_by_zone_operator.csv", index=False)

    center = [zones.geometry.centroid.y.median(), zones.geometry.centroid.x.median()]
    maps = [("all", grouped)] + [(operator.lower(), data.drop(columns="operator")) for operator, data in by_operator.groupby("operator")]
    for name, data in maps:
        enriched = zones.merge(data, left_on="zone_id", right_on="end_zone", how="left")
        map_obj = folium.Map(location=center, zoom_start=12, tiles="cartodbpositron")
        add_parking_layer(map_obj, enriched, f"Average parking duration (min) - {name.title()}")
        map_obj.save(paths.maps_dir / f"parking_by_zone_{name}.html")

    for hour in [7, 8, 9, 12, 13, 17, 18, 19]:
        hourly = parking[parking["end_hour"].eq(hour)].dropna(subset="end_zone").groupby("end_zone").agg(avg_parking_min=("parking_min", "mean"), n_events=("parking_min", "size")).reset_index()
        enriched = zones.merge(hourly, left_on="zone_id", right_on="end_zone", how="left")
        map_obj = folium.Map(location=center, zoom_start=12, tiles="cartodbpositron")
        add_parking_layer(map_obj, enriched, f"Average parking duration (min) - {hour:02d}:00")
        map_obj.save(paths.maps_dir / f"parking_by_zone_hour_{hour:02d}.html")


def save_financial_summary(trips: pd.DataFrame, paths: ProjectPaths) -> None:
    financial = trips.copy()
    financial["billable_min"] = np.ceil(financial["duration_min"]).clip(lower=0)
    financial["unlock_fee"] = financial["operator"].map(lambda op: TARIFFS[op]["unlock_eur"])
    financial["per_min_fee"] = financial["operator"].map(lambda op: TARIFFS[op]["per_min_eur"])
    financial["revenue"] = financial["unlock_fee"] + financial["per_min_fee"] * financial["billable_min"]
    financial["variable_cost"] = sum(COSTS_EUR[key] for key in ["charging_per_ride", "repairs_per_ride", "card_fees_per_ride", "support_per_ride", "insurance_per_ride"])
    financial["date"] = financial["start_time"].dt.date
    summary = financial.groupby("operator", as_index=False).agg(n_trips=("trip_id", "size"), revenue_total=("revenue", "sum"), variable_cost_total=("variable_cost", "sum"), n_scooters=("vehicle_id", "nunique"), n_days=("date", "nunique"))
    amort_per_day = COSTS_EUR["scooter_purchase"] / COSTS_EUR["scooter_lifespan_years"] / 365
    summary["broader_cost_total"] = COSTS_EUR["city_licenses_total"] + COSTS_EUR["designated_parking_total"] + summary["n_scooters"] * (COSTS_EUR["annual_fee_per_scooter"] * summary["n_days"] / 365 + COSTS_EUR["daily_fee_per_scooter"] * summary["n_days"] + amort_per_day * summary["n_days"])
    summary["total_cost"] = summary["variable_cost_total"] + summary["broader_cost_total"]
    summary["profit"] = summary["revenue_total"] - summary["total_cost"]
    summary["profit_margin"] = summary["profit"] / summary["revenue_total"]
    summary.sort_values("profit", ascending=False).to_csv(paths.tables_dir / "financial_summary.csv", index=False)


def run(paths: ProjectPaths) -> None:
    ensure_output_dirs(paths)
    raw_trips = load_trips(paths)
    trips, quality = clean_trips(raw_trips)
    trips = add_time_fields(trips)
    quality.to_csv(paths.tables_dir / "data_quality_report.csv", index=False)
    trips.to_csv(paths.tables_dir / "cleaned_trips.csv", index=False)
    save_temporal_figures(trips, paths)
    zones = load_zones(paths)
    od_trips = build_od(trips, zones)
    save_od_outputs(od_trips, zones, paths)
    save_heatmaps(od_trips, paths)
    parking = calculate_parking(trips, zones)
    save_parking_outputs(parking, zones, paths)
    save_financial_summary(trips, paths)
    print(f"Analysis complete. Outputs saved to: {paths.results_dir}")


def main() -> None:
    project_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Run the Turin micromobility analysis.")
    parser.add_argument("--data-root", type=Path, default=project_root / "Practical part" / "Work")
    parser.add_argument("--results-dir", type=Path, default=project_root / "results")
    args = parser.parse_args()
    run(ProjectPaths(data_root=args.data_root, results_dir=args.results_dir))
