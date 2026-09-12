# QGIS Web Agent MVP

对 [wing-show.com/projects/qgis-web-agent](https://wing-show.com/projects/qgis-web-agent/) 的极简复现。
核心链路：**自然语言 → 服务器端真实 QGIS 计算 → 结果上图可下载**。

设计原则：只保留核心，不做降级与回退。大模型不可用时直接报错；地理计算只走真实 QGIS。

## 已实现

- 单页前端：Leaflet 地图（OSM 底图）+ 聊天框 + 图层面板（隐藏/定位/下载/删除）
- 数据：加载示例道路（武汉）、上传单个 GeoJSON
- 智能体：通义千问 Qwen function calling，工具 `buffer`（缓冲区）、`total_length`（长度统计）
- 计算：真实 QGIS（`qgis_process` + `native:buffer` / `native:reprojectlayer`）

## 快速开始

```powershell
cd D:\论文\qgis-web-agent-mvp

# 1. 生成示例数据（首次）
python scripts/make_sample.py

# 2. 启动服务（用 python -m，避免 uvicorn 不在 PATH 的问题）
python -m uvicorn backend.main:app --reload --port 8000
```

浏览器打开 <http://127.0.0.1:8000>，点「加载示例道路」，然后输入：

- 把示例道路往两边各扩 200 米
- 统计示例道路的总长度

## 验证

```powershell
python scripts/check_qgis.py    # 验证 QGIS 引擎（调用应用实际使用的引擎）
```

## 配置（.env）

项目根目录 `.env`（已 gitignore）：

```
DASHSCOPE_API_KEY=sk-...
QGIS_PROCESS_PATH=D:\Program Files\QGIS 3.44.14\bin\qgis_process-qgis-ltr.bat
```

可选环境变量：

| 变量 | 说明 |
|---|---|
| `QGIS_PROCESS_FLAGS` | 追加给 qgis_process 的参数，默认空 |
| `QGIS_WEB_AGENT_MODEL` | 覆盖模型名，默认 `qwen-plus` |

## 计算引擎

`QgisEngine` 通过 `qgis_process` 调用 QGIS 原生算法，缓冲走三步：

```
native:reprojectlayer（→ EPSG:3857，米制）
native:buffer（DISTANCE 单位与图层 CRS 一致）
native:reprojectlayer（→ EPSG:4326）
```

- 验证环境：QGIS 3.44.14，入口 `...\QGIS 3.44.14\bin\qgis_process-qgis-ltr.bat`
- Windows 上是 `.bat` 包装脚本（负责设置 QGIS 运行环境），不是直接调 `.exe`
- 长度统计是平凡度量，直接用 GeoPandas 计算，不必走 QGIS

## 目录结构

```
qgis-web-agent-mvp/
├── backend/
│   ├── main.py      # FastAPI 路由 + .env 加载 + 静态前端
│   ├── agent.py     # 工具定义 + Qwen function calling
│   ├── engine.py    # QgisEngine（qgis_process 调用）
│   └── store.py     # 内存图层存储
├── frontend/
│   └── index.html   # Leaflet + 聊天 + 图层面板
├── scripts/
│   ├── make_sample.py
│   └── check_qgis.py
├── data/
│   └── sample_roads.geojson  # 运行 make_sample.py 生成
└── requirements.txt
```

## 已明确简化（相对原项目）

- 无 SSE 流式（用同步请求 + 事后刷新图层列表）
- 无框选、无 shapefile 多文件、无栅格、无 MCP 协议、无会话管理、无鉴权
- 底图用 OSM（原项目用天地图/百度，需 key 与火星坐标纠偏）
- 距离运算用 `EPSG:3857`（武汉纬度约放大 16%，追求精度可改 `EPSG:4525`）
