"""智能体层：工具定义 + 通义千问 function calling。"""
from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from . import analytics
from . import engine as engine_mod
from . import geodata, raster

QWEN_MODEL = os.environ.get("QGIS_WEB_AGENT_MODEL", "qwen-plus")
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def _fn(name: str, description: str, properties: dict, required: list) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


_LAYER_ID = {"type": "string", "description": "图层 id（见系统提示中的图层列表）"}

TOOLS = [
    _fn("inspect_layer",
        "查看图层的概况：要素数、几何类型、都有哪些属性字段及样例值。"
        "在做按字段筛选或字段统计前，先用它确认字段名。",
        {"layer_id": _LAYER_ID}, ["layer_id"]),

    _fn("layer_to_geojson",
        "把图层导出为 GeoJSON，返回下载地址。",
        {"layer_id": _LAYER_ID}, ["layer_id"]),

    _fn("buffer",
        "对图层做缓冲区分析，生成面图层。distance_m 单位为米。",
        {"layer_id": _LAYER_ID,
         "distance_m": {"type": "number", "description": "缓冲距离（米）"}},
        ["layer_id", "distance_m"]),

    _fn("points_along_lines",
        "沿线段按固定间距生成采样点，用于把线离散成点。distance_m 为点间距（米）。",
        {"layer_id": _LAYER_ID,
         "distance_m": {"type": "number", "description": "采样点间距（米）"},
         "start_offset": {"type": "number", "description": "起点偏移（米），默认 0"},
         "end_offset": {"type": "number", "description": "终点偏移（米），默认 0"}},
        ["layer_id", "distance_m"]),

    _fn("clip",
        "用另一个图层作为范围，裁剪出落在其中的部分。overlay_layer_id 是作为裁剪范围的面图层。",
        {"layer_id": _LAYER_ID,
         "overlay_layer_id": {"type": "string", "description": "作为裁剪范围的面图层 id"}},
        ["layer_id", "overlay_layer_id"]),

    _fn("extract_by_attribute",
        "按属性值筛选要素。operator 只能是 = != > >= < <= 之一。"
        "字段名请先用 inspect_layer 确认。",
        {"layer_id": _LAYER_ID,
         "field": {"type": "string", "description": "字段名"},
         "operator": {"type": "string", "description": "比较符：= != > >= < <="},
         "value": {"type": "string", "description": "比较值"}},
        ["layer_id", "field", "operator", "value"]),

    _fn("total_length",
        "统计线图层所有要素的总长度（米）。",
        {"layer_id": _LAYER_ID}, ["layer_id"]),

    _fn("field_stats",
        "统计某个字段的取值分布与数值特征（计数、去重数、最常见取值、最大最小均值等）。"
        "字段名请先用 inspect_layer 确认。",
        {"layer_id": _LAYER_ID,
         "field": {"type": "string", "description": "字段名"}},
        ["layer_id", "field"]),

    _fn("reproject",
        "把图层重投影到指定坐标系。target_crs 形如 EPSG:4525。"
        "注意结果坐标不再是经纬度，不可直接叠加在地图上。",
        {"layer_id": _LAYER_ID,
         "target_crs": {"type": "string", "description": "目标坐标系，如 EPSG:4525"}},
        ["layer_id", "target_crs"]),

    _fn("load_layer",
        "加载服务器 data 目录里的数据文件为图层。filename 为文件名，如 sample_roads.geojson。",
        {"filename": {"type": "string", "description": "data 目录下的文件名"}},
        ["filename"]),

    _fn("get_osm_roads",
        "按地名从 OpenStreetMap 现取道路数据（需联网，可能要等十几秒）。"
        "地名建议写成「市+区」，如 武汉市青山区。",
        {"location": {"type": "string", "description": "地名，如 武汉市青山区"}},
        ["location"]),

    _fn("get_admin_boundary",
        "按地名获取行政区划边界多边形（来自 OSM，需联网）。",
        {"location": {"type": "string", "description": "地名，如 湖北省、武汉市洪山区"}},
        ["location"]),

    _fn("get_dem",
        "获取指定地名的 DEM 高程栅格（真实高程数据，需联网）。"
        "得到栅格图层后才能做坡度、坡向、山体阴影。",
        {"location": {"type": "string", "description": "地名，如 武汉市洪山区"},
         "zoom": {"type": "integer", "description": "瓦片层级 11~13，越大越精细也越慢，默认 12"}},
        ["location"]),

    _fn("slope",
        "对 DEM 栅格计算坡度。输入必须是栅格图层（先用 get_dem）。",
        {"layer_id": _LAYER_ID,
         "z_factor": {"type": "number", "description": "高程放大系数，默认 1"}},
        ["layer_id"]),

    _fn("aspect",
        "对 DEM 栅格计算坡向。输入必须是栅格图层（先用 get_dem）。",
        {"layer_id": _LAYER_ID,
         "z_factor": {"type": "number", "description": "高程放大系数，默认 1"}},
        ["layer_id"]),

    _fn("hillshade",
        "对 DEM 栅格计算山体阴影。输入必须是栅格图层（先用 get_dem）。",
        {"layer_id": _LAYER_ID,
         "z_factor": {"type": "number", "description": "高程放大系数，默认 1"},
         "azimuth": {"type": "number", "description": "光源方位角，默认 315"}},
        ["layer_id"]),

    _fn("render_png",
        "把图层渲染成 PNG 图片：栅格图层直接导出图片，矢量图层先栅格化再出图。",
        {"layer_id": _LAYER_ID}, ["layer_id"]),
]


class Agent:
    def __init__(self, store, engine, data_dir: Path):
        self.store = store
        self.engine = engine
        self.data_dir = Path(data_dir)

    # ---------- 工具执行 ----------
    def _run_tool(self, name: str, args: dict) -> str:
        try:
            return json.dumps(self._dispatch(name, args), ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False)

    def _layer(self, args: dict):
        lid = args.get("layer_id")
        layer = self.store.get(lid)
        if layer is None:
            raise ValueError(f"图层不存在：{lid}。可用图层见系统提示。")
        return layer

    def _new_layer(self, name: str, geojson: dict, crs: str = "EPSG:4326") -> dict:
        lid = self.store.add(name=name, geojson=geojson, crs=crs)
        return {"ok": True, "new_layer_id": lid, "new_layer_name": name,
                "feature_count": len(geojson.get("features", [])), "crs": crs}

    def _new_raster(self, name: str, tif_path: str) -> dict:
        png = str(raster.workdir() / f"{uuid4().hex[:8]}.png")
        raster.raster_to_png(tif_path, png)
        bounds = raster.raster_bounds_wgs84(tif_path)
        lid = self.store.add_raster(name, tif_path, png, bounds)
        return {"ok": True, "new_layer_id": lid, "new_layer_name": name,
                "layer_type": "raster", "bounds": bounds}

    def _raster_input(self, args: dict):
        layer = self._layer(args)
        if layer.get("layer_type") != "raster":
            raise ValueError(
                f"「{layer['name']}」不是栅格图层；坡度/坡向/山体阴影只能作用于栅格，"
                "请先用 get_dem 获取 DEM")
        return layer

    def _dispatch(self, name: str, args: dict) -> dict:
        if name == "inspect_layer":
            layer = self._layer(args)
            if layer.get("layer_type") == "raster":
                return {"ok": True, "name": layer["name"], "layer_type": "raster",
                        "crs": layer["crs"], "bounds": layer["bounds"],
                        "note": "栅格图层，可做 slope / aspect / hillshade / render_png"}
            return {"ok": True,
                    **analytics.inspect_layer(layer, layer["geojson"])}

        if name == "layer_to_geojson":
            layer = self._layer(args)
            if layer.get("layer_type") == "raster":
                return {"ok": True, "note": "栅格图层不能转 GeoJSON，请用 render_png 出图",
                        "png_url": f"/api/layers/{layer['id']}/file"}
            return {"ok": True,
                    "note": "本系统图层内部即 GeoJSON（EPSG:4326），可直接下载",
                    "feature_count": layer["feature_count"],
                    "download_url": f"/api/layers/{layer['id']}/download"}

        if name == "buffer":
            layer = self._layer(args)
            d = float(args["distance_m"])
            result = self.engine.buffer(layer["geojson"], d)
            return self._new_layer(f"{layer['name']}缓冲{d:g}米", result)

        if name == "points_along_lines":
            layer = self._layer(args)
            d = float(args["distance_m"])
            result = self.engine.points_along_lines(
                layer["geojson"], d,
                float(args.get("start_offset") or 0),
                float(args.get("end_offset") or 0))
            return self._new_layer(f"{layer['name']}采样点{d:g}米", result)

        if name == "clip":
            layer = self._layer(args)
            overlay = self._layer({"layer_id": args.get("overlay_layer_id")})
            result = self.engine.clip(layer["geojson"], overlay["geojson"])
            return self._new_layer(f"{layer['name']}裁剪", result)

        if name == "extract_by_attribute":
            layer = self._layer(args)
            result = self.engine.extract_by_attribute(
                layer["geojson"], args["field"], args["operator"], str(args["value"]))
            return self._new_layer(
                f"{layer['name']}筛选{args['field']}{args['operator']}{args['value']}", result)

        if name == "total_length":
            layer = self._layer(args)
            length = analytics.total_length(layer["geojson"])
            return {"ok": True, "total_length_m": round(length, 2),
                    "total_length_km": round(length / 1000, 4),
                    "feature_count": layer["feature_count"]}

        if name == "field_stats":
            layer = self._layer(args)
            return {"ok": True, **analytics.field_stats(layer["geojson"], args["field"])}

        if name == "reproject":
            layer = self._layer(args)
            target = args["target_crs"]
            result = self.engine.reproject(layer["geojson"], target)
            return self._new_layer(f"{layer['name']}重投影{target}", result, crs=target)

        if name == "load_layer":
            filename = os.path.basename(args["filename"])
            path = self.data_dir / filename
            if not path.exists():
                available = [p.name for p in self.data_dir.glob("*") if p.is_file()]
                raise ValueError(f"文件不存在：{filename}。data 目录下有：{available}")
            geojson = json.loads(path.read_text(encoding="utf-8"))
            return self._new_layer(Path(filename).stem, geojson)

        if name in ("get_osm_roads", "get_admin_boundary"):
            loc = args["location"]
            if name == "get_osm_roads":
                return self._new_layer(f"{loc}OSM道路", geodata.osm_roads(loc))
            return self._new_layer(f"{loc}边界", geodata.admin_boundary(loc))

        if name == "get_dem":
            loc = args["location"]
            west, south, east, north, _ = geodata.geocode_bbox(loc)
            tif = raster.fetch_dem(west, south, east, north, int(args.get("zoom") or 12))
            return self._new_raster(f"{loc}DEM", tif)

        if name in ("slope", "aspect", "hillshade"):
            layer = self._raster_input(args)
            out = str(raster.workdir() / f"{name}_{uuid4().hex[:8]}.tif")
            z = float(args.get("z_factor") or 1)
            if name == "slope":
                self.engine.slope(layer["tif_path"], out, z)
                label = f"{layer['name']}坡度"
            elif name == "aspect":
                self.engine.aspect(layer["tif_path"], out, z)
                label = f"{layer['name']}坡向"
            else:
                self.engine.hillshade(layer["tif_path"], out, z,
                                      float(args.get("azimuth") or 315))
                label = f"{layer['name']}山体阴影"
            return self._new_raster(label, out)

        if name == "render_png":
            layer = self._layer(args)
            if layer.get("layer_type") == "raster":
                return {"ok": True, "note": "栅格图层已渲染为图片",
                        "png_url": f"/api/layers/{layer['id']}/file",
                        "bounds": layer["bounds"]}
            tif = str(raster.workdir() / f"render_{uuid4().hex[:8]}.tif")
            self.engine.rasterize(layer["geojson"], tif)
            return self._new_raster(f"{layer['name']}渲染图", tif)

        raise ValueError(f"未知工具：{name}")

    # ---------- 系统提示 ----------
    def _system_prompt(self) -> str:
        layers = self.store.list()
        if layers:
            lines = "\n".join(
                f"- {l['name']}（id={l['id']}，"
                + ("栅格图层" if l.get("layer_type") == "raster"
                   else f"{l.get('feature_count', 0)} 要素")
                + f"，{l.get('crs')}）"
                for l in layers)
        else:
            lines = "（暂无图层，可用 load_layer 加载示例数据）"
        files = [p.name for p in self.data_dir.glob("*") if p.is_file()]
        return (
            "你是一个 GIS 助手，帮用户对地图图层做地理处理。\n"
            "规则：\n"
            "1. 只能用提供的工具完成计算，不要凭空声称算出了结果。\n"
            "2. 用户提到某图层时，用下面列表里的 id 调用工具。\n"
            "3. 需要按字段处理时，先用 inspect_layer 确认字段名，再调用相关工具。\n"
            "4. 工具返回 new_layer_id 时，向用户说明新图层已生成。\n"
            f"\n当前可用图层：\n{lines}\n"
            f"\ndata 目录下可加载的文件：{files}"
        )

    # ---------- function calling 循环 ----------
    def chat(self, text: str) -> dict:
        from openai import OpenAI
        client = OpenAI(
            api_key=os.environ.get("DASHSCOPE_API_KEY", ""), base_url=DASHSCOPE_BASE_URL)
        messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": text},
        ]
        logs = []
        try:
            for _ in range(6):
                resp = client.chat.completions.create(
                    model=QWEN_MODEL, messages=messages, tools=TOOLS, tool_choice="auto")
                msg = resp.choices[0].message
                if not msg.tool_calls:
                    return {"reply": msg.content or "", "tool_logs": logs}
                messages.append(msg)
                for tc in msg.tool_calls:
                    args = json.loads(tc.function.arguments or "{}")
                    result = self._run_tool(tc.function.name, args)
                    logs.append({"name": tc.function.name, "args": args, "result": result})
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    })
            return {"reply": "（达到最大工具调用轮数，仍未得到最终答复）", "tool_logs": logs}
        except Exception as e:
            return {"reply": f"调用大模型失败：{e}", "tool_logs": logs}
