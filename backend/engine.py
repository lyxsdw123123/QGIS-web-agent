"""地理计算：调用 qgis_process 执行 QGIS 原生算法。

QGIS 入口由 QGIS_PROCESS_PATH 指定（见 .env），额外参数由 QGIS_PROCESS_FLAGS 指定。
算法 id 与参数名均对照本机 QGIS 3.44 的 `qgis_process list` / `help` 确认。
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

# native:extractbyattribute 的 OPERATOR 是枚举，命令行传序号
OPERATORS = {"=": 0, "!=": 1, ">": 2, ">=": 3, "<": 4, "<=": 5}


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
        args = " ".join(f'{k}="{v}"' for k, v in params.items())
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

    # ---------- 通用矢量算法通道 ----------
    def _vector_op(self, alg: str, params: dict, *, metric: bool = False) -> dict:
        """跑一次矢量算法并返回结果 GeoJSON。

        params 里值为 dict 的项视为 GeoJSON 输入（会自动落盘为文件），其余为标量参数。
        metric=True 时把主输入先转到米制 CRS、结果再转回经纬度，用于按距离运算的算法。
        """
        with tempfile.TemporaryDirectory() as d:
            args: dict = {}
            first_input = True
            for k, v in params.items():
                if isinstance(v, dict):
                    p = os.path.join(d, f"{k}.geojson")
                    with open(p, "w", encoding="utf-8") as f:
                        json.dump(v, f, ensure_ascii=False)
                    if metric and first_input:
                        mp = os.path.join(d, f"{k}_m.gpkg")
                        self._run("native:reprojectlayer",
                                  {"INPUT": p, "TARGET_CRS": METRIC_CRS, "OUTPUT": mp})
                        p = mp
                    args[k] = p
                    first_input = False
                else:
                    args[k] = v

            if metric:
                mid = os.path.join(d, "mid.gpkg")
                args["OUTPUT"] = mid
                self._run(alg, args)
                out = os.path.join(d, "out.geojson")
                self._run("native:reprojectlayer",
                          {"INPUT": mid, "TARGET_CRS": "EPSG:4326", "OUTPUT": out})
            else:
                out = os.path.join(d, "out.geojson")
                args["OUTPUT"] = out
                self._run(alg, args)

            with open(out, encoding="utf-8") as f:
                return json.load(f)

    # ---------- 具体算法 ----------
    def buffer(self, geojson: dict, distance_m: float) -> dict:
        return self._vector_op("native:buffer",
                               {"INPUT": geojson, "DISTANCE": distance_m}, metric=True)

    def points_along_lines(self, geojson: dict, distance_m: float,
                           start_offset: float = 0, end_offset: float = 0) -> dict:
        return self._vector_op("native:pointsalonglines", {
            "INPUT": geojson, "DISTANCE": distance_m,
            "START_OFFSET": start_offset, "END_OFFSET": end_offset,
        }, metric=True)

    def clip(self, geojson: dict, overlay: dict) -> dict:
        return self._vector_op("native:clip", {"INPUT": geojson, "OVERLAY": overlay})

    def extract_by_attribute(self, geojson: dict, field: str,
                             operator: str, value: str) -> dict:
        op = OPERATORS.get(operator)
        if op is None:
            raise ValueError(f"不支持的操作符：{operator}（可选 {list(OPERATORS)}）")
        return self._vector_op("native:extractbyattribute", {
            "INPUT": geojson, "FIELD": field, "OPERATOR": op, "VALUE": value,
        })

    def reproject(self, geojson: dict, target_crs: str) -> dict:
        """重投影。注意结果坐标系为 target_crs，不再是经纬度。"""
        with tempfile.TemporaryDirectory() as d:
            inp = os.path.join(d, "in.geojson")
            with open(inp, "w", encoding="utf-8") as f:
                json.dump(geojson, f, ensure_ascii=False)
            out = os.path.join(d, "out.geojson")
            self._run("native:reprojectlayer",
                      {"INPUT": inp, "TARGET_CRS": target_crs, "OUTPUT": out})
            with open(out, encoding="utf-8") as f:
                return json.load(f)

    # ---------- 栅格算法 ----------
    def _raster_op(self, alg: str, params: dict, out_path: str) -> str:
        args = dict(params)
        args["OUTPUT"] = out_path
        self._run(alg, args)
        return out_path

    def slope(self, dem_path: str, out_path: str, z_factor: float = 1.0) -> str:
        return self._raster_op("native:slope",
                               {"INPUT": dem_path, "Z_FACTOR": z_factor}, out_path)

    def aspect(self, dem_path: str, out_path: str, z_factor: float = 1.0) -> str:
        return self._raster_op("native:aspect",
                               {"INPUT": dem_path, "Z_FACTOR": z_factor}, out_path)

    def hillshade(self, dem_path: str, out_path: str, z_factor: float = 1.0,
                  azimuth: float = 315) -> str:
        return self._raster_op("native:hillshade",
                               {"INPUT": dem_path, "Z_FACTOR": z_factor,
                                "AZIMUTH": azimuth}, out_path)

    def rasterize(self, geojson: dict, out_path: str, width: int = 1024) -> str:
        """把矢量图层栅格化成图片，用于出图。"""
        with tempfile.TemporaryDirectory() as d:
            inp = os.path.join(d, "in.geojson")
            with open(inp, "w", encoding="utf-8") as f:
                json.dump(geojson, f, ensure_ascii=False)
            self._run("gdal:rasterize", {
                "INPUT": inp, "UNITS": 0, "WIDTH": width, "BURN": 1,
                "OUTPUT": out_path})
        return out_path


def create_engine() -> QgisEngine:
    cmd = os.environ.get("QGIS_PROCESS_PATH", "").strip()
    if not cmd:
        raise RuntimeError("未配置 QGIS_PROCESS_PATH（见 .env），无法调用 qgis_process")
    if not os.path.exists(cmd):
        raise RuntimeError(f"QGIS_PROCESS_PATH 指向的路径不存在：{cmd}")
    return QgisEngine(cmd, os.environ.get("QGIS_PROCESS_FLAGS", "").strip())
