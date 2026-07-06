# 数据目录说明

本项目当前主数据线改为 **Porto 出租车 OD 查询 + OpenStreetMap 路网**。

旧的 USA-road DIMACS 数据、SNAP roadNet-PA 数据、合成查询负载和对应旧图表已经从数据目录中移除。后续实验默认围绕 Porto 数据展开。

## 目录结构

```text
data/
  README.md
  compressed/
    porto/
      uci_porto_taxi.zip
      train.csv.zip
      portugal-latest.osm.pbf
  raw/
    porto/
      说明.md
  processed/
    porto/
      波尔图起终点样本_10万.csv
      波尔图道路节点.csv
      波尔图道路边.csv
      波尔图起终点节点查询_10万.csv
      波尔图可用起终点节点查询_200米.csv
      波尔图起终点吸附质量报告.md
  plots/
    波尔图起终点热力图_10万.png
    波尔图道路底图起终点热力图_10万.png
```

说明：

- `compressed/porto/` 保存原始下载文件，体积较大，已经在 `.gitignore` 中忽略，不提交到仓库。
- `raw/porto/` 保存数据来源、许可和处理说明。
- `processed/porto/` 保存可直接用于实验的中间数据。
- `plots/` 保存 OD 热力图和道路底图可视化。

## 当前数据来源

| 数据 | 来源 | 作用 |
| --- | --- | --- |
| Porto taxi trajectory dataset | UCI Machine Learning Repository | 提供真实出租车轨迹，用轨迹首尾点构造 OD 查询 |
| Portugal OSM PBF | Geofabrik / OpenStreetMap | 提供 Porto 区域道路节点和道路边 |

更详细的来源、许可和处理命令见：

```text
data/raw/porto/说明.md
```

## 当前可用数据

| 文件 | 含义 |
| --- | --- |
| `processed/porto/波尔图起终点样本_10万.csv` | 从 Porto taxi 轨迹中抽取的 10 万条有效 OD 经纬度 |
| `processed/porto/波尔图道路节点.csv` | 从 OSM PBF 抽取的 Porto 道路节点，包含经纬度和平面坐标 |
| `processed/porto/波尔图道路边.csv` | 从 OSM PBF 抽取的 Porto 有向道路边，边权为米 |
| `processed/porto/波尔图起终点节点查询_10万.csv` | 10 万条 OD 吸附到最近道路节点后的完整结果 |
| `processed/porto/波尔图可用起终点节点查询_200米.csv` | 起终点吸附距离都不超过 200 米的查询，建议作为第一版实验查询集 |
| `processed/porto/波尔图起终点吸附质量报告.md` | 吸附成功率、吸附距离分布和路网规模统计 |

当前吸附结果概要：

| 指标 | 数值 |
| --- | ---: |
| 路网节点数 | 133,839 |
| 有向边数 | 221,589 |
| 原始查询数 | 100,000 |
| 200 米内可用查询数 | 98,082 |
| 200 米内可用占比 | 98.08% |

## 图表

| 文件 | 含义 |
| --- | --- |
| `plots/波尔图起终点热力图_10万.png` | 经纬度坐标上的 OD 起点/终点热力图 |
| `plots/波尔图道路底图起终点热力图_10万.png` | 叠加本地 OSM 道路底图后的 OD 起点/终点热力图 |

## 推荐实验入口

第一版最短路 baseline 建议使用：

```text
processed/porto/波尔图道路节点.csv
processed/porto/波尔图道路边.csv
processed/porto/波尔图可用起终点节点查询_200米.csv
```

也就是说，下一步应该读取道路边表建图，再对可用查询表中的 `origin_node` 和 `dest_node` 跑 Dijkstra 或双向 Dijkstra。
