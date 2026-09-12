"""图层分析：不经过 QGIS 的纯 Python 计算与元数据检查。

长度、字段统计、图层概况这些不是几何运算，直接用 Python 处理 GeoJSON 即可，
比让 QGIS 跑一圈再解析输出更简单可靠。
"""
from __future__ import annotations

from collections import Counter

METRIC_CRS = "EPSG:3857"


def total_length(geojson: dict) -> float:
    """线图层总长度（米）。"""
    import geopandas as gpd
    gdf = gpd.GeoDataFrame.from_features(geojson, crs="EPSG:4326").to_crs(METRIC_CRS)
    return float(gdf.geometry.length.sum())


def field_stats(geojson: dict, field: str) -> dict:
    """某字段的统计：计数、数值统计、出现最多的取值。"""
    feats = geojson.get("features", [])
    if feats and not any(field in (f.get("properties") or {}) for f in feats):
        raise ValueError(f"字段不存在：{field}（可先用 inspect_layer 查看字段名）")
    values = [f.get("properties", {}).get(field) for f in feats]
    present = [v for v in values if v is not None]
    nums = [v for v in present if isinstance(v, (int, float)) and not isinstance(v, bool)]

    out = {
        "field": field,
        "feature_count": len(feats),
        "non_null_count": len(present),
        "distinct_count": len({str(v) for v in present}),
        "top_values": [{"value": k, "count": n}
                       for k, n in Counter(str(v) for v in present).most_common(5)],
    }
    if nums:
        out["numeric"] = {
            "count": len(nums),
            "min": min(nums),
            "max": max(nums),
            "sum": round(sum(nums), 4),
            "mean": round(sum(nums) / len(nums), 4),
        }
    return out


def inspect_layer(meta: dict, geojson: dict) -> dict:
    """图层概况：要素数、几何类型、字段及样例值。"""
    feats = geojson.get("features", [])
    geom_types = Counter(f["geometry"]["type"] for f in feats if f.get("geometry"))

    fields: dict = {}
    for f in feats[:20]:
        for k, v in (f.get("properties") or {}).items():
            if k not in fields:
                fields[k] = v
    return {
        "name": meta.get("name"),
        "feature_count": len(feats),
        "geometry_types": dict(geom_types),
        "fields": {k: f"样例：{v}" for k, v in fields.items()},
    }
