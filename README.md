# QGIS Web Agent MVP

复现自原作 [QGIS Web Agent · 对话式地理处理](https://wing-show.com/projects/qgis-web-agent/)（作者：张翼 / Wing's Space）。
核心链路：**自然语言 → 服务器端真实 QGIS 计算 → 结果上图可下载**。

设计原则：只保留核心，不做降级与回退。大模型不可用时直接报错；地理计算只走真实 QGIS。

## 已实现

- 单页前端：Leaflet 地图（OSM 底图）+ 聊天框 + 图层面板（隐藏/定位/下载/删除）
  矢量走 GeoJSON 渲染，栅格以 PNG 图片叠加
- 智能体：通义千问 Qwen function calling，**17 个 GIS 工具**
- 计算：真实 QGIS（`qgis_process`）
- 流式：SSE 实时推送（工具卡片实时推进、新图层即时上图）

## 快速开始

```powershell
cd D:\论文\qgis-web-agent-mvp

# 1. 生成示例数据（首次）
python scripts/make_sample.py

# 2. 启动服务（用 python -m，避免 uvicorn 不在 PATH 的问题）
python -m uvicorn backend.main:app --reload --port 8000
```

浏览器打开 <http://127.0.0.1:8000>，然后可以直接用自然语言提问：

- 加载示例道路，看看有哪些字段，筛选主干道并统计长度
- 获取武汉市江汉区的 DEM，计算坡度和山体阴影
- 下载武汉市青山区的 OSM 道路，做 200 米缓冲
- 取湖北省边界，把道路裁剪进去

## 17 个工具

| 工具 | 说明 | 实现 |
|---|---|---|
| `inspect_layer` | 图层概况：要素数、几何类型、字段及样例值 | 纯 Python |
| `layer_to_geojson` | 导出 GeoJSON，返回下载地址 | — |
| `buffer` | 缓冲区（米） | `native:buffer` |
| `points_along_lines` | 沿线按间距生成采样点（米） | `native:pointsalonglines` |
| `clip` | 用面图层裁剪 | `native:clip` |
| `extract_by_attribute` | 按属性筛选（`= != > >= < <=`） | `native:extractbyattribute` |
| `reproject` | 重投影到指定坐标系 | `native:reprojectlayer` |
| `render_png` | 出图（矢量先栅格化） | `gdal:rasterize` → PNG |
| `total_length` | 线图层总长度 | 纯 Python |
| `field_stats` | 字段取值分布与数值统计 | 纯 Python |
| `load_layer` | 加载 data 目录下的文件 | — |
| `get_osm_roads` | 按地名取 OSM 道路 | Overpass（多镜像重试） |
| `get_admin_boundary` | 按地名取行政区划边界 | Nominatim |
| `get_dem` | 获取 DEM 高程栅格 | AWS Terrain Tiles |
| `slope` | 坡度 | `native:slope` |
| `aspect` | 坡向 | `native:aspect` |
| `hillshade` | 山体阴影 | `native:hillshade` |

> 坡度/坡向/山体阴影只作用于栅格图层，需先用 `get_dem` 获取 DEM。

## 验证

```powershell
python scripts/check_qgis.py    # 验证 QGIS 引擎
```

## 配置（.env）

项目根目录 `.env`（已 gitignore）：

```
DASHSCOPE_API_KEY=sk-...
QGIS_PROCESS_PATH=D:\Program Files\QGIS 3.44.14\bin\qgis_process-qgis-ltr.bat
```

| 环境变量 | 说明 |
|---|---|
| `QGIS_PROCESS_FLAGS` | 追加给 qgis_process 的参数，默认空 |
| `QGIS_WEB_AGENT_MODEL` | 覆盖模型名，默认 `qwen-plus` |

## 计算引擎

`QgisEngine` 通过 `qgis_process` 调用 QGIS 原生算法。按距离运算的矢量算法走米制往返：

```
native:reprojectlayer（→ EPSG:3857，米制）
<算法，如 native:buffer>
native:reprojectlayer（→ EPSG:4326）
```

因为 `native:buffer` 的 `DISTANCE` 单位是图层自身 CRS 的单位，经纬度图层下不转投影会得到错误结果。

- 验证环境：QGIS 3.44.14，入口 `...\QGIS 3.44.14\bin\qgis_process-qgis-ltr.bat`
- Windows 上是 `.bat` 包装脚本（负责设置 QGIS 运行环境），不是直接调 `.exe`
- 算法 id / 参数名 / 枚举值均用 `qgis_process list`、`qgis_process help <算法>` 查证

## 目录结构

```
qgis-web-agent-mvp/
├── backend/
│   ├── main.py       # FastAPI 路由 + .env 加载 + 静态前端
│   ├── agent.py      # 17 个工具定义 + function calling 循环
│   ├── engine.py     # QgisEngine（矢量/栅格算法、栅格化）
│   ├── analytics.py  # 纯 Python：长度、字段统计、图层检查
│   ├── raster.py     # DEM 获取 + 栅格转 PNG + Web Mercator 换算
│   ├── geodata.py    # 地名解析、行政区划边界、OSM 道路
│   └── store.py      # 图层存储（矢量/栅格）
├── frontend/
│   └── index.html    # Leaflet + 聊天 + 图层面板
├── scripts/
│   ├── make_sample.py
│   └── check_qgis.py
├── data/
│   └── sample_roads.geojson
└── requirements.txt
```

## 已简化（相对原项目）

- 无框选/点选、无 shapefile 多文件上传、无 MCP 协议、无会话管理、无鉴权
- 底图用 OSM（原项目用天地图/百度，需 key 与火星坐标纠偏）
- 距离运算用 `EPSG:3857`（武汉纬度约放大 16%，追求精度可改 `EPSG:4525`）
- DEM 瓦片单次上限 16 张，范围过大时会提示缩小范围或降低 zoom
