"""内存图层存储（MVP 单用户，进程内 dict，重启即清空）。"""
from __future__ import annotations

import uuid


class LayerStore:
    # meta() 不返回的重字段
    _HEAVY = ("geojson", "tif_path", "png_path")

    def __init__(self):
        self._layers = {}  # id -> 图层字典

    def add(self, name: str, geojson: dict, layer_type: str = "vector",
            crs: str = "EPSG:4326") -> str:
        lid = uuid.uuid4().hex[:12]
        self._layers[lid] = {
            "id": lid,
            "name": name,
            "layer_type": layer_type,
            "crs": crs,
            "geojson": geojson,
            "feature_count": len(geojson.get("features", [])),
        }
        return lid

    def add_raster(self, name: str, tif_path: str, png_path: str,
                   bounds: list) -> str:
        lid = uuid.uuid4().hex[:12]
        self._layers[lid] = {
            "id": lid,
            "name": name,
            "layer_type": "raster",
            "crs": "EPSG:4326",
            "tif_path": tif_path,
            "png_path": png_path,
            "bounds": bounds,          # [[south, west], [north, east]]
        }
        return lid

    def get(self, lid: str):
        return self._layers.get(lid)

    def meta(self, lid: str):
        layer = self._layers.get(lid)
        if layer is None:
            return None
        return {k: v for k, v in layer.items() if k not in self._HEAVY}

    def list(self):
        return [self.meta(lid) for lid in self._layers]

    def delete(self, lid: str):
        return self._layers.pop(lid, None)
