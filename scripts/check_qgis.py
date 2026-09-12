"""检查 QGIS 引擎是否可用：直接调用应用实际使用的引擎，跑一次真实缓冲。

运行：python scripts/check_qgis.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.main import engine   # 导入即加载 .env 并自动探测引擎

LINE = {
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature",
        "properties": {"id": 1},
        "geometry": {"type": "LineString", "coordinates": [[114.30, 30.50], [114.32, 30.52]]},
    }],
}


def main():
    print("engine =", engine.name)
    print("cmd    =", getattr(engine, "cmd", "(不适用)"))
    print("flags  =", getattr(engine, "flags", "(不适用)") or "(无)")

    if engine.name != "qgis_process":
        print("\n提示：当前未启用 QGIS 引擎。检查 .env 的 QGIS_PROCESS_PATH，"
              "或设 QGIS_WEB_AGENT_ENGINE=qgis 强制启用。")

    try:
        result = engine.buffer(LINE, 100)
    except Exception as e:
        print("\n缓冲失败：", e)
        print("\n结论：QGIS 引擎未跑通 [FAIL]")
        return

    feats = result.get("features", [])
    types = {f["geometry"]["type"] for f in feats}
    print(f"\n输出：{len(feats)} 要素，几何类型 {types}")
    print("结论：引擎可用 [OK]")


if __name__ == "__main__":
    main()
