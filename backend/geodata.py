"""外部地理数据：地名解析、行政区划边界、OSM 道路。

数据源均为公开服务：
  - Nominatim（地名 → 范围 / 边界多边形）
  - Overpass API（OSM 道路要素）
使用时遵守其公共使用条款：带 User-Agent、单次少量请求。
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

NOMINATIM = "https://nominatim.openstreetmap.org/search"
# 多个 Overpass 镜像，单个超时/繁忙时依次重试
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
]
UA = {"User-Agent": "qgis-web-agent/0.1 (demo)"}

# 只要可通行道路，排除人行道/步道/自行车道等
ROAD_FILTER = ("motorway|trunk|primary|secondary|tertiary|unclassified|"
               "residential|service|living_street|road")


def _get_json(url: str, timeout: int = 60):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def geocode_bbox(place: str):
    """地名 → (west, south, east, north, 规范名)。"""
    q = urllib.parse.urlencode({"q": place, "format": "json", "limit": 1})
    items = _get_json(f"{NOMINATIM}?{q}")
    if not items:
        raise ValueError(f"没有找到地名：{place}（建议写成「市+区」形式，避免重名）")
    it = items[0]
    s, n, w, e = (float(v) for v in it["boundingbox"])   # 顺序：south, north, west, east
    return w, s, e, n, it["display_name"]


def admin_boundary(place: str) -> dict:
    """地名 → 行政区划边界（GeoJSON FeatureCollection，取自 OSM）。"""
    q = urllib.parse.urlencode({
        "q": place, "format": "json", "limit": 1, "polygon_geojson": 1})
    items = _get_json(f"{NOMINATIM}?{q}")
    if not items:
        raise ValueError(f"没有找到地名：{place}")
    it = items[0]
    geom = it.get("geojson")
    if not geom or geom.get("type") not in ("Polygon", "MultiPolygon"):
        raise ValueError(f"「{place}」没有可用的边界多边形（可能不是行政区）")
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"name": it.get("display_name", place), "osm_type": it.get("osm_type")},
            "geometry": geom,
        }],
    }


def osm_roads(place: str) -> dict:
    """地名 → 该范围内的 OSM 道路（GeoJSON FeatureCollection）。"""
    w, s, e, n, name = geocode_bbox(place)
    query = (f"[out:json][timeout:180];"
             f'way["highway"~"^({ROAD_FILTER})$"]({s},{w},{n},{e});'
             f"out geom;")
    data = urllib.parse.urlencode({"data": query}).encode()

    osm, errors = None, []
    for endpoint in OVERPASS_MIRRORS:
        try:
            req = urllib.request.Request(endpoint, data=data, headers=UA)
            with urllib.request.urlopen(req, timeout=240) as resp:
                osm = json.loads(resp.read().decode("utf-8"))
            break
        except Exception as exc:
            errors.append(f"{endpoint.split('/')[2]}: {exc}")
    if osm is None:
        raise ValueError(
            f"Overpass 查询失败（范围过大或服务繁忙，可换更小的地名）：{'；'.join(errors)}")

    features = []
    for el in osm.get("elements", []):
        if el.get("type") != "way":
            continue
        geom = el.get("geometry") or []
        coords = [[p["lon"], p["lat"]] for p in geom
                  if p.get("lon") is not None and p.get("lat") is not None]
        if len(coords) < 2:
            continue
        props = {"osm_id": el.get("id")}
        props.update(el.get("tags") or {})
        features.append({
            "type": "Feature",
            "properties": props,
            "geometry": {"type": "LineString", "coordinates": coords},
        })
    if not features:
        raise ValueError(f"「{place}」范围内没有取到道路数据")
    return {"type": "FeatureCollection",
            "features": features,
            "_source": f"OSM via Overpass（{name}）"}
