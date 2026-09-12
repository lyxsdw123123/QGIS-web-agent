"""生成示例道路数据（武汉市中心片区，WGS-84 经纬度）。

运行：python scripts/make_sample.py
产物：data/sample_roads.geojson
"""
from __future__ import annotations

import json
import random
from pathlib import Path

random.seed(7)

# 武汉市中心片区 bbox：[lng_min, lat_min, lng_max, lat_max]
BBOX = [114.25, 30.47, 114.45, 30.62]

features = []
for i in range(60):
    n_points = random.randint(3, 9)
    lng = random.uniform(BBOX[0], BBOX[2])
    lat = random.uniform(BBOX[1], BBOX[3])
    coords = [[round(lng, 6), round(lat, 6)]]
    for _ in range(n_points - 1):
        # 沿大致方向随机游走，模拟道路走势；越界则折返
        lng += random.uniform(-0.008, 0.008)
        lat += random.uniform(-0.006, 0.006)
        lng = max(BBOX[0], min(BBOX[2], lng))
        lat = max(BBOX[1], min(BBOX[3], lat))
        coords.append([round(lng, 6), round(lat, 6)])
    features.append({
        "type": "Feature",
        "properties": {
            "id": i,
            "name": f"road_{i:02d}",
            "kind": random.choice(["主干道", "次干道", "支路"]),
        },
        "geometry": {"type": "LineString", "coordinates": coords},
    })

fc = {"type": "FeatureCollection", "features": features}
out = Path(__file__).resolve().parent.parent / "data" / "sample_roads.geojson"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(fc, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"OK: wrote {len(features)} features -> {out}")
