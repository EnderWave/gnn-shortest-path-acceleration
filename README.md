# AIC Porto 数据准备

本仓库当前使用 Porto 出租车轨迹构造 OD 查询，并使用 OpenStreetMap Portugal
路网作为最短路实验图。原始下载文件体积较大，因此不会提交到 Git 仓库。

在仓库根目录运行下面的命令即可一键准备数据：

```bash
python scripts/prepare_porto_data.py
```

Windows 上如果 `python` 不在 PATH 中，可以改用：

```powershell
py scripts\prepare_porto_data.py
```

脚本会自动创建 `.venv/`，安装 `requirements.txt` 中的依赖，下载 UCI Porto
taxi 数据集和 Geofabrik Portugal OSM PBF，然后生成：

- `data/processed/porto/波尔图起终点样本_10万.csv`
- `data/processed/porto/波尔图道路节点.csv`
- `data/processed/porto/波尔图道路边.csv`
- `data/processed/porto/波尔图可用起终点节点查询_200米.csv`
- `data/processed/porto/波尔图起终点吸附质量报告.md`

常用参数：

```bash
python scripts/prepare_porto_data.py --od-limit 10000
python scripts/prepare_porto_data.py --force
python scripts/prepare_porto_data.py --skip-road-plot
```

- `--od-limit 10000`：只抽取 1 万条 OD 样本，适合快速测试。
- `--force`：重新下载并重新生成已有结果。
- `--skip-road-plot`：跳过道路底图热力图，减少运行时间。

完整数据准备预计占用数 GB 磁盘空间。数据来源包括 UCI Taxi Service
Trajectory Prediction Challenge, ECML PKDD 2015 和 Geofabrik Portugal OSM
extract。

## 运行最短路 baseline

数据准备完成后，可以运行 Dijkstra 和双向 Dijkstra baseline：

```bash
.venv/bin/python scripts/run_baselines.py
```

默认读取 `data/processed/porto/` 下的道路节点、道路边和 200 米吸附阈值内的
可用 OD 查询。输出结果位于：

- `results/baselines/porto_allqueries_summary.csv`
- `results/baselines/porto_allqueries_details.csv`

当前 98,082 条 Porto 可用 OD 查询全量 baseline 结果：

| 方法 | 可达查询 | 平均耗时 ms | p95 耗时 ms | 平均展开节点 | 正确率 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Dijkstra | 97009/98082 | 17.976 | 92.645 | 24831.37 | 1.000000 |
| 双向 Dijkstra | 97009/98082 | 8.339 | 37.341 | 10741.70 | 1.000000 |
