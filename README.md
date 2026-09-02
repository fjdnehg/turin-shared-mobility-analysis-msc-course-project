# Turin Shared Micromobility Analysis

Reproducible Python workflow for analysing shared e-scooter trips in Turin. It combines Lime, Voi and Bird trip records, cleans and standardises them, then produces temporal, spatial, parking-duration and financial outputs.

## Outputs

- Weekly, monthly and yearly demand figures.
- Origin-destination tables and top-flow maps.
- Origin and destination heatmaps by time period.
- Parking-duration choropleths overall, by operator and by hour. Lower parking durations are green; higher durations are red.
- A financial summary by operator using clearly stated assumed tariffs and costs.

## Project layout

```
run_analysis.py                         # Command-line entry point
src/micromobility_analysis/config.py    # Paths and analysis assumptions
src/micromobility_analysis/pipeline.py  # Reproducible workflow
results/                                # Generated locally; not committed
Practical part/Work/                    # Local raw data and zone shapefile
```

## Setup and run

Create and activate a virtual environment, then install the dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Run the full workflow from the repository root:

```bash
turin-micromobility
```

By default it reads data from `Practical part/Work` and writes all generated files to `results`. Both paths can be changed:

```bash
turin-micromobility --data-root /path/to/data --results-dir /path/to/results
```

`PYTHONPATH=src python run_analysis.py` remains available if you prefer not to install the project.

## Data requirements

The raw input files are deliberately excluded from Git because they may be large or have sharing restrictions. The expected local structure is:

```
Practical part/Work/
  Operator A_Lime/Torino_Corse24-25.csv
  Operator B_Voi/DATINOLEGGI_combined.csv
  Operator C_Bird/Bird_Torino_2024_2025_combined.csv
  Zonestatistiche_group/zone_statistiche_group.shp
```

## Notes on interpretation

Parking duration is the time from a trip ending to the next trip beginning for the same operator and vehicle. Intervals below zero and above 24 hours are excluded only from parking analyses. Revenue and cost estimates use the full cleaned trip dataset, not the parking subset. Tariffs and operating costs are assumptions for comparative exploration, not audited operator accounts.

## Portfolio framing

This repository demonstrates data engineering for heterogeneous operator data, geospatial O-D analysis, interactive cartography and transparent scenario-based business analysis. Add 2-4 representative figures from `results/figures` or `results/maps` to this README after running it, keeping raw trip data out of the public repository.
