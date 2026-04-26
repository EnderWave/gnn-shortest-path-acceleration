# 图数据集说明

这个目录存放用于最短路实验的公开路网数据。当前数据已经同时保留了
原始压缩文件和解压后的文本文件。后续写代码时优先读取 `raw/` 下的
解压文本文件；`compressed/` 下的 `.gz` 文件只作为原始备份。

## 目录结构

```text
data/
  README.md
  compressed/
    dimacs/
      small/
        USA-road-d.NY.gr.gz
        USA-road-d.NY.co.gz
      medium/
        USA-road-d.BAY.gr.gz
        USA-road-d.BAY.co.gz
      large/
        USA-road-d.COL.gr.gz
        USA-road-d.COL.co.gz
    snap/
      roadNet-PA.txt.gz
  raw/
    dimacs/
      small/
        USA-road-d.NY.gr
        USA-road-d.NY.co
      medium/
        USA-road-d.BAY.gr
        USA-road-d.BAY.co
      large/
        USA-road-d.COL.gr
        USA-road-d.COL.co
    snap/
      roadNet-PA.txt
```

文件后缀含义：

| 后缀 | 含义 |
| --- | --- |
| `.gz` | 原始压缩文件，保留备份 |
| `.gr` | DIMACS 带权有向边文件 |
| `.co` | DIMACS 节点坐标文件 |
| `.txt` | SNAP 普通边表文件 |

## 当前数据集

| 规模 | 数据集 | 来源 | 节点数 | 边/弧数 | 解压文件位置 | 推荐用途 |
| --- | --- | --- | ---: | ---: | --- | --- |
| 小 | USA-road-d.NY | DIMACS | 264,346 | 733,846 | `raw/dimacs/small/` | 第一版原型，最推荐 |
| 中 | USA-road-d.BAY | DIMACS | 321,270 | 800,172 | `raw/dimacs/medium/` | 中等规模对比 |
| 大 | USA-road-d.COL | DIMACS | 435,666 | 1,057,066 | `raw/dimacs/large/` | 稍大规模验证 |
| 额外大图 | roadNet-PA | SNAP | 1,088,092 | 3,083,796 | `raw/snap/` | 大规模拓扑测试 |

建议先使用 `USA-road-d.NY`。它是当前 DIMACS 三个图中最小的，但仍然是
真实带权路网，足够完成第一版最短路、历史查询和热点统计实验。

## DIMACS 数据怎么用

来源：https://www.diag.uniroma1.it/~challenge9/download.shtml

DIMACS 是当前主实验数据。每个地区有两个文件：

| 文件 | 作用 |
| --- | --- |
| `raw/dimacs/small/USA-road-d.NY.gr` | 小规模 NY 道路连接关系和边权 |
| `raw/dimacs/small/USA-road-d.NY.co` | 小规模 NY 节点经纬度坐标 |
| `raw/dimacs/medium/USA-road-d.BAY.gr` | 中规模 BAY 道路连接关系和边权 |
| `raw/dimacs/medium/USA-road-d.BAY.co` | 中规模 BAY 节点经纬度坐标 |
| `raw/dimacs/large/USA-road-d.COL.gr` | 大规模 COL 道路连接关系和边权 |
| `raw/dimacs/large/USA-road-d.COL.co` | 大规模 COL 节点经纬度坐标 |

`compressed/dimacs/` 下有同名 `.gz` 压缩包，按同样的小、中、大目录保存。

### `.gr` 边文件结构

`.gr` 文件是带权有向图，主要有三类行：

```text
c 注释行
p sp 节点数 边/弧数
a 起点节点 终点节点 边权
```

例子：

```text
p sp 264346 733846
a 1 2 803
a 2 1 803
```

含义：

| 字段 | 解释 |
| --- | --- |
| `p sp 264346 733846` | 这个图有 264,346 个节点、733,846 条有向弧 |
| `a 1 2 803` | 从节点 1 到节点 2 有一条边，边权为 803 |
| `a 2 1 803` | 从节点 2 到节点 1 也有一条边，边权为 803 |

注意：DIMACS 里很多真实双向道路会被保存成两条有向边，所以后续读图时
可以直接按有向边处理，不需要自己额外补反向边。

### `.co` 坐标文件结构

`.co` 文件保存节点坐标，主要有三类行：

```text
c 注释行
p aux sp co 节点数
v 节点编号 经度 纬度
```

例子：

```text
p aux sp co 264346
v 1 -73530767 41085396
```

含义：

| 字段 | 解释 |
| --- | --- |
| `v` | 表示这是一个节点坐标行 |
| `1` | 节点编号 |
| `-73530767` | 放大后的经度 |
| `41085396` | 放大后的纬度 |

经纬度通常按 `1e6` 放大保存。实际使用时可以这样转换：

```text
longitude = -73530767 / 1e6 = -73.530767
latitude  =  41085396 / 1e6 =  41.085396
```

坐标的用途：

| 用途 | 说明 |
| --- | --- |
| A* 启发函数 | 用节点间几何距离估计到目标的剩余距离 |
| 热点查询生成 | 按地理区域选择高频起点和终点 |
| 可视化 | 画原始路网、热点节点、路径经过频率 |
| 图分区 | 可以辅助构造地理区域或对比学习式分区 |

### Python 读取 DIMACS 的基本思路

读 `.gr` 时，只需要处理 `a` 开头的行：

```python
adj = {}

with open("data/raw/dimacs/small/USA-road-d.NY.gr", "r", encoding="utf-8") as f:
    for line in f:
        if line.startswith("a "):
            _, u, v, w = line.split()
            u, v, w = int(u), int(v), int(w)
            adj.setdefault(u, []).append((v, w))
```

读 `.co` 时，只需要处理 `v` 开头的行：

```python
coords = {}

with open("data/raw/dimacs/small/USA-road-d.NY.co", "r", encoding="utf-8") as f:
    for line in f:
        if line.startswith("v "):
            _, node, lon, lat = line.split()
            coords[int(node)] = (int(lon) / 1e6, int(lat) / 1e6)
```

读完以后：

| 变量 | 含义 |
| --- | --- |
| `adj[u]` | 节点 `u` 的所有出边，格式为 `(邻居节点, 边权)` |
| `coords[u]` | 节点 `u` 的经纬度，格式为 `(经度, 纬度)` |

## SNAP roadNet-PA 数据怎么用

来源：https://snap.stanford.edu/data/roadNet-PA.html

SNAP 的 `roadNet-PA.txt` 是一个普通边表文件，文件结构更简单：

```text
# 注释行
FromNodeId ToNodeId
```

例子：

```text
0 1
0 6309
1 0
```

含义是存在：

| 起点 | 终点 |
| ---: | ---: |
| 0 | 1 |
| 0 | 6309 |
| 1 | 0 |

这个数据没有边权、没有坐标，所以不建议作为第一版主实验数据。如果要用于
最短路实验，可以先把每条边的权重统一设为 `1`，把它当成无权图或单位权图。

### Python 读取 SNAP 的基本思路

```python
adj = {}

with open("data/raw/snap/roadNet-PA.txt", "r", encoding="utf-8") as f:
    for line in f:
        if line.startswith("#"):
            continue
        u, v = map(int, line.split())
        adj.setdefault(u, []).append((v, 1))
```

## 第一版实验推荐流程

第一版不要急着上 GNN，先把“图 + 历史查询 + baseline”跑通。

推荐顺序：

| 步骤 | 目标 | 建议文件 |
| --- | --- | --- |
| 1 | 读取真实带权路网 | `raw/dimacs/small/USA-road-d.NY.gr` |
| 2 | 读取节点坐标 | `raw/dimacs/small/USA-road-d.NY.co` |
| 3 | 随机或按热点生成 OD 查询 | 起点 `origin`、终点 `destination` |
| 4 | 用 Dijkstra 计算历史最短路 | 得到每条历史路径 |
| 5 | 统计历史行为特征 | 节点经过次数、边经过次数、起终点频率 |
| 6 | 构造节点/边特征 | 为后续 GNN 或聚类做输入 |
| 7 | 做 baseline 对比 | 原始 Dijkstra、A*、简单地理分块 |

历史查询建议不要用完全均匀随机。为了贴近真实系统，可以先模拟成：

| 查询类型 | 比例 | 含义 |
| --- | ---: | --- |
| 热点到热点 | 70% | 高频区域之间反复查询 |
| 热点到普通区域 | 20% | 常见出发地到分散目的地 |
| 普通随机查询 | 10% | 保留冷门查询，防止方法只适合热点 |

这样生成出来的历史负载，才能体现你的研究主题：利用真实或模拟的查询偏好
来重构图，而不是只根据静态拓扑做普通图划分。

## 后续可以生成的中间数据

建议后面不要直接反复扫描原始文本文件，而是生成更方便程序读取的中间文件：

```text
data/processed/
  ny_edges.csv
  ny_nodes.csv
  ny_queries_train.csv
  ny_queries_test.csv
  ny_node_features.csv
  ny_edge_features.csv
```

建议字段：

| 文件 | 字段示例 |
| --- | --- |
| `ny_edges.csv` | `src,dst,weight` |
| `ny_nodes.csv` | `node,lon,lat` |
| `ny_queries_train.csv` | `origin,destination,count,query_type` |
| `ny_node_features.csv` | `node,start_count,end_count,pass_count,hot_score` |
| `ny_edge_features.csv` | `src,dst,pass_count,weight` |

这些中间数据就是后续 GNN、聚类、图粗化和预处理策略选择的基础。
