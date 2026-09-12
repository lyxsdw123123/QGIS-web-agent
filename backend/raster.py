"""栅格处理：DEM 获取与栅格转图片。

DEM 来自 AWS Terrain Tiles（terrarium 编码，公开免 key），转成 GeoTIFF 供 QGIS 使用。
栅格本身不能被浏览器显示，统一转成 PNG 后交给前端做图片叠加。
"""
from __future__ import annotations

import atexit
import hashlib
import io
import math
import shutil
import tempfile
import urllib.request
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.transform import from_bounds
from rasterio.warp import transform_bounds

TERRARIUM_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
MAX_TILES = 16          # 限制单次下载瓦片数，避免范围过大
R = 6378137.0           # Web Mercator 半径（米）

_WORK = None


def workdir() -> Path:
    """进程级临时工作目录（放 DEM 与中间栅格），进程退出时清理。"""
    global _WORK
    if _WORK is None:
        _WORK = Path(tempfile.mkdtemp(prefix="qgis-web-agent-"))
        atexit.register(shutil.rmtree, _WORK, True)
    return _WORK


# ---------- Web Mercator 瓦片换算 ----------
def _lonlat_to_tile(lon: float, lat: float, z: int):
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    lat_r = math.radians(lat)
    y = (1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * n
    return x, y


def _tile_to_lonlat(x: float, y: float, z: int):
    n = 2 ** z
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lon, lat


def _merc(lon: float, lat: float):
    return R * math.radians(lon), R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


# ---------- DEM ----------
def fetch_dem(west: float, south: float, east: float, north: float, zoom: int = 12) -> str:
    """下载指定范围的 DEM，写成 EPSG:3857 的 GeoTIFF，返回文件路径。"""
    x0f, y0f = _lonlat_to_tile(west, north, zoom)   # 左上角
    x1f, y1f = _lonlat_to_tile(east, south, zoom)   # 右下角
    tx0, ty0 = math.floor(x0f), math.floor(y0f)
    tx1, ty1 = math.floor(x1f), math.floor(y1f)
    nx, ny = tx1 - tx0 + 1, ty1 - ty0 + 1
    if nx * ny > MAX_TILES:
        raise ValueError(
            f"范围过大：该范围需要 {nx * ny} 张瓦片（上限 {MAX_TILES}），请缩小范围或降低 zoom")

    tiles = np.zeros((ny * 256, nx * 256), dtype=np.float32)
    for iy in range(ny):
        for ix in range(nx):
            url = TERRARIUM_URL.format(z=zoom, x=tx0 + ix, y=ty0 + iy)
            req = urllib.request.Request(url, headers={"User-Agent": "qgis-web-agent"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                img = Image.open(io.BytesIO(resp.read())).convert("RGB")
            rgb = np.asarray(img, dtype=np.float32)
            # terrarium 编码：高程 = R*256 + G + B/256 - 32768
            tiles[iy * 256:(iy + 1) * 256, ix * 256:(ix + 1) * 256] = (
                rgb[:, :, 0] * 256.0 + rgb[:, :, 1] + rgb[:, :, 2] / 256.0 - 32768.0)

    west_al, north_al = _tile_to_lonlat(tx0, ty0, zoom)
    east_al, south_al = _tile_to_lonlat(tx1 + 1, ty1 + 1, zoom)
    minx, miny = _merc(west_al, south_al)
    maxx, maxy = _merc(east_al, north_al)

    key = hashlib.md5(f"{west_al:.6f},{south_al:.6f},{east_al:.6f},{north_al:.6f},{zoom}"
                      .encode()).hexdigest()[:12]
    out = workdir() / f"dem_{key}.tif"

    h, w = tiles.shape
    with rasterio.open(out, "w", driver="GTiff", height=h, width=w, count=1,
                       dtype="float32", crs="EPSG:3857",
                       transform=from_bounds(minx, miny, maxx, maxy, w, h)) as dst:
        dst.write(tiles, 1)
    return str(out)


def raster_bounds_wgs84(path: str):
    """返回栅格的经纬度范围 [[south, west], [north, east]]。"""
    with rasterio.open(path) as src:
        west, south, east, north = transform_bounds(
            src.crs, "EPSG:4326", *src.bounds)
    return [[south, west], [north, east]]


def raster_to_png(tif_path: str, png_path: str) -> str:
    """把栅格转成 PNG（按 2%~98% 分位拉伸成灰度），供浏览器叠加显示。"""
    with rasterio.open(tif_path) as src:
        data = src.read(1, masked=True).astype("float32").filled(np.nan)
    if not np.isfinite(data).any():
        raise ValueError("栅格无有效像素")
    lo, hi = np.nanpercentile(data, 2), np.nanpercentile(data, 98)
    if not np.isfinite(lo) or hi <= lo:
        lo, hi = float(np.nanmin(data)), float(np.nanmax(data))
    span = (hi - lo) or 1.0
    # 栅格边缘可能是 nodata（NaN），先归零再量化成 8 位灰度
    norm = np.nan_to_num(np.clip((data - lo) / span, 0, 1), nan=0.0)
    gray = (norm * 255).astype("uint8")
    Image.fromarray(gray, mode="L").save(png_path)
    return png_path
