# 面向历史 OD 负载的无路径监督精确最短路压缩索引

本项目研究如何只使用历史起点、终点和道路图，在固定索引预算下选择值得压缩的
连通区域，从而减少未来最短路查询开销。项目不使用历史最短路径作为监督标签，
不让神经网络预测路径；压缩表由精确算法离线物化，在线结果必须与原图最短路完全
一致。

## 研究计划

```text
Porto OD 与 OSM 路网
        ↓
精确最短路基线与全量评测框架
        ↓
随机区域、OD 热点区域等传统压缩基线
        ↓
离线物化压缩图并验证真实在线收益
        ↓
参数与预算扫描，确定公平比较条件
        ↓
GNN 学习节点和候选区域的压缩价值
        ↓
同预算对比、消融实验和跨城市验证
```

GNN 位于第 4 步。它不替代 Dijkstra，而是根据道路拓扑和历史 OD 需求，为节点或
候选区域输出压缩价值分数。模型选出区域后，仍由现有精确预处理程序构建 shortcut
和物化压缩图，再由双向 Dijkstra 完成在线查询。

## 研究进度与成果

| 步骤 | 状态 | 已有成果 |
| --- | --- | --- |
| 1. 数据与评测框架 | 已完成 | 构建 Porto 道路图和 98,082 条可用 OD；实现 Dijkstra、双向 Dijkstra、逐查询明细和正确性评测。 |
| 2. 传统压缩与物化查询 | 已完成 | 实现随机、OD 热点区域；离线构建节点三态表、shortcut 和压缩图；全量配对实验正确率 100%，在线耗时下降。 |
| 3. 参数与预算扫描 | 脚本已完成，待全量运行 | 已实现可断点续跑的控制变量实验脚本；需要其他研究者完成长时间运行，再根据结果确定推荐参数和公平预算。 |
| 4. GNN 区域价值模型 | 未开始 | 需要实现节点特征、需求场传播、候选区域评分、无路径监督训练目标和预算选择。 |
| 5. 最终对比实验 | 未开始 | 需要在相同预算下比较 GNN、随机区域和 OD 热点区域，并完成消融、稳定性和跨城市实验。 |

当前物化压缩图的全量配对结果：

| 方法 | 基线平均耗时 | 压缩平均耗时 | 在线耗时变化 | P95 变化 | 展开节点变化 | 正确率 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 随机区域 | 27.378 ms | 25.885 ms | **-5.45%** | -4.97% | -9.08% | 100% |
| OD 热点区域 | 28.122 ms | 27.235 ms | **-3.15%** | -2.07% | -5.57% | 100% |

这证明离线物化区域压缩图能够降低平均在线查询开销，但尚未证明 GNN 有效。目前
只有传统启发式结果；下一步应先完成参数与预算扫描，再在相同压缩预算下训练和比较
GNN。最终验证结果见
[`results/regions/porto_98082queries_r200_s512_paired_final_report.md`](results/regions/porto_98082queries_r200_s512_paired_final_report.md)。

## 数据准备

本仓库使用 Porto 出租车轨迹构造 OD 查询，并使用 OpenStreetMap Portugal 路网作为
最短路实验图。原始下载文件体积较大，因此不会提交到 Git 仓库。

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

## 运行物化压缩图实验

离线构建随机区域和 OD 热点区域的压缩图，并运行普通全量实验：

```bash
python scripts/run_region_experiments.py --region-count 200 --region-size 512
```

最终性能结论应使用配对验证。它会在同一工作进程中连续执行每条 OD 的基线与
压缩查询，并交替执行顺序，减少机器负载和缓存差异对计时的影响：

```bash
python scripts/verify_materialized_queries.py --region-count 200 --region-size 512
```

两个脚本默认使用全部 CPU 核心并运行全部 98,082 条可用 OD。区域生成、shortcut
计算和压缩图构建均属于离线预处理，不计入在线查询耗时。最终结果位于：

- `results/regions/porto_98082queries_r200_s512_paired_summary.csv`
- `results/regions/porto_98082queries_r200_s512_paired_details.csv`
- `results/regions/porto_98082queries_r200_s512_paired_final_report.md`

## 运行参数与预算扫描

正式扫描采用控制变量法：固定区域大小为 `512`，依次测试区域数量
`50、100、200、400`；再固定区域数量为 `200`，依次测试区域大小
`128、256、512、1024`。随机区域每组运行 5 个随机种子，OD 热点区域每组运行
一次，共 42 组。每组都使用全部 98,082 条 OD，并在同一进程内配对执行基线和
压缩查询。

先查看计划执行的配置，不会启动实验：

```bash
python scripts/run_parameter_scan.py --dry-run
```

确认后运行正式扫描：

```bash
python scripts/run_parameter_scan.py
```

Windows 上也可以运行：

```powershell
py scripts\run_parameter_scan.py
```

脚本默认使用全部 CPU 核心，预计需要数小时，具体时间取决于机器。每完成一组就会
立即把结果写入：

- `results/parameter_scan/porto_parameter_scan.csv`

如果运行中断，重新执行同一条命令即可继续，已经写入 CSV 的配置会被自动跳过。
只有确定要清空已有进度并从头运行时才使用：

```bash
python scripts/run_parameter_scan.py --restart
```

CSV 包含每组配置的实际区域数、shortcut 数、压缩图规模、回退率、预处理时间、
平均与 P95 在线耗时、展开节点变化、查询加速比例和正确率。全量运行完成后保留该
CSV，由本项目维护者负责汇总随机种子的均值和波动、比较控制变量结果、筛选有效
配置，并给出参数与预算扫描阶段的最终结论。
