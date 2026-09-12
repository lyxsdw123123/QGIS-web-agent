"""内存图层存储（MVP 单用户，进程内 dict，重启即清空）。"""
from __future__ import annotations

import uuid


class LayerStore:
    def __init__(self):
        self._layers = {}  # id -> {"id","name","geojson","feature_count","layer_type"}

    def add(self, name: str, geojson: dict, layer_type: str = "vector") -> str:
        lid = uuid.uuid4().hex[:12]
        self._layers[lid] = {
            "id": lid,
            "name": name,
            "geojson": geojson,
            "feature_count": len(geojson.get("features", [])),
            "layer_type": layer_type,
        }
        return lid

    def get(self, lid: str):
        return self._layers.get(lid)

    def meta(self, lid: str):
        layer = self._layers.get(lid)
        if layer is None:
            return None
        return {k: v for k, v in layer.items() if k != "geojson"}

    def list(self):
        return [self.meta(lid) for lid in self._layers]

    def delete(self, lid: str):
        return self._layers.pop(lid, None)
