"""地理计算：调用 qgis_process 执行 QGIS 原生算法。

QGIS 入口由 QGIS_PROCESS_PATH 指定（见 .env），额外参数由 QGIS_PROCESS_FLAGS 指定。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile

# 距离运算用的投影坐标系（单位：米）。
# EPSG:3857 全球通用；国内局部演示可换 EPSG:4525（CGCS2000 / 3度带，中央经线 114E）更准。
METRIC_CRS = "EPSG:3857"


class QgisEngine:
    """通过 qgis_process 调用 QGIS 原生算法。

    命令语法已对照 QGIS 3.44 的 `qgis_process --help` 确认：
        qgis_process run <算法> -- PARAM=VALUE
    """
    name = "qgis_process"

    def __init__(self, cmd: str, flags: str = ""):
        self.cmd = cmd
        self.flags = flags

    def _run(self, alg: str, params: dict) -> str:
        args = " ".join(f"{k}={v}" for k, v in params.items())
        parts = [f'"{self.cmd}"']
        if self.flags:
            parts.append(self.flags)
        parts += ["run", alg, "--", args]
        proc = subprocess.run(" ".join(parts), capture_output=True, text=True, shell=True)
        if proc.returncode != 0:
            # 报错里常混着 HTML，剥掉标签再抛
            msg = re.sub(r"<[^>]+>", "", proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(msg or "qgis_process failed")
        return proc.stdout

    def buffer(self, geojson: dict, distance_m: float) -> dict:
        with tempfile.TemporaryDirectory() as d:
            inp = os.path.join(d, "in.geojson")
            reproj = os.path.join(d, "reproj.gpkg")
            buf = os.path.join(d, "buf.gpkg")
            out = os.path.join(d, "out.geojson")
            with open(inp, "w", encoding="utf-8") as f:
                json.dump(geojson, f, ensure_ascii=False)
            # 先重投影到米制 CRS，再缓冲（DISTANCE 单位与图层 CRS 一致），最后转回经纬度
            self._run("native:reprojectlayer",
                      {"INPUT": inp, "TARGET_CRS": METRIC_CRS, "OUTPUT": reproj})
            self._run("native:buffer",
                      {"INPUT": reproj, "DISTANCE": distance_m, "OUTPUT": buf})
            self._run("native:reprojectlayer",
                      {"INPUT": buf, "TARGET_CRS": "EPSG:4326", "OUTPUT": out})
            with open(out, encoding="utf-8") as f:
                return json.load(f)


def compute_total_length(geojson: dict) -> float:
    """线图层总长度（米）。长度是平凡度量，直接用 GeoPandas 计算，不必走 QGIS。"""
    import geopandas as gpd
    gdf = gpd.GeoDataFrame.from_features(geojson, crs="EPSG:4326")
    gdf = gdf.to_crs(METRIC_CRS)
    return float(gdf.geometry.length.sum())


def create_engine() -> QgisEngine:
    cmd = os.environ.get("QGIS_PROCESS_PATH", "").strip() or "qgis_process"
    return QgisEngine(cmd, os.environ.get("QGIS_PROCESS_FLAGS", "").strip())
