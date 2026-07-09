# AIC Porto Data Setup

This repository uses Porto taxi OD queries and an OpenStreetMap Portugal road
extract. Raw downloads are large and are intentionally not committed.

Run the one-step setup from the repository root.

```bash
python scripts/prepare_porto_data.py
```

On Windows, if `python` is not on PATH, use:

```powershell
py scripts\prepare_porto_data.py
```

The script creates `.venv/`, installs `requirements.txt`, downloads the
UCI Porto taxi archive and Geofabrik Portugal OSM PBF, then generates:

- `data/processed/porto/波尔图起终点样本_10万.csv`
- `data/processed/porto/波尔图道路节点.csv`
- `data/processed/porto/波尔图道路边.csv`
- `data/processed/porto/波尔图可用起终点节点查询_200米.csv`
- `data/processed/porto/波尔图起终点吸附质量报告.md`

Useful options:

```bash
python scripts/prepare_porto_data.py --od-limit 10000
python scripts/prepare_porto_data.py --force
python scripts/prepare_porto_data.py --skip-road-plot
```

Expected disk use is several GB. Data sources: UCI Taxi Service Trajectory
Prediction Challenge, ECML PKDD 2015; Geofabrik Portugal OSM extract.
