"""智能体层：工具定义 + 通义千问 function calling。"""
from __future__ import annotations

import json
import os

from . import engine as engine_mod

QWEN_MODEL = os.environ.get("QGIS_WEB_AGENT_MODEL", "qwen-plus")
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "buffer",
            "description": "对指定图层做缓冲区分析。distance_m 单位为米。",
            "parameters": {
                "type": "object",
                "properties": {
                    "layer_id": {"type": "string", "description": "要缓冲的图层 id"},
                    "distance_m": {"type": "number", "description": "缓冲距离（米）"},
                },
                "required": ["layer_id", "distance_m"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "total_length",
            "description": "统计线图层所有要素的总长度（米）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "layer_id": {"type": "string", "description": "要统计的线图层 id"},
                },
                "required": ["layer_id"],
            },
        },
    },
]


class Agent:
    def __init__(self, store, engine):
        self.store = store
        self.engine = engine

    # ---------- 工具执行 ----------
    def _run_tool(self, name: str, args: dict) -> str:
        lid = args.get("layer_id")
        layer = self.store.get(lid)
        if layer is None:
            return json.dumps({"error": f"图层不存在：{lid}。可用图层见系统提示。"}, ensure_ascii=False)

        if name == "buffer":
            distance = float(args.get("distance_m", 0))
            result = self.engine.buffer(layer["geojson"], distance)
            new_id = self.store.add(name=f"{layer['name']}缓冲{distance:g}米", geojson=result)
            return json.dumps({
                "ok": True,
                "new_layer_id": new_id,
                "feature_count": len(result.get("features", [])),
            }, ensure_ascii=False)

        if name == "total_length":
            length = engine_mod.compute_total_length(layer["geojson"])
            return json.dumps({
                "ok": True,
                "total_length_m": round(length, 2),
                "total_length_km": round(length / 1000, 4),
                "feature_count": layer["feature_count"],
            }, ensure_ascii=False)

        return json.dumps({"error": f"未知工具：{name}"}, ensure_ascii=False)

    # ---------- 系统提示 ----------
    def _system_prompt(self) -> str:
        layers = self.store.list()
        if layers:
            lines = "\n".join(
                f"- {l['name']}（id={l['id']}，{l['feature_count']} 要素）" for l in layers)
        else:
            lines = "（暂无图层）"
        return (
            "你是一个 GIS 助手，帮用户对地图图层做地理处理。\n"
            "规则：\n"
            "1. 只能用提供的工具完成计算，不要凭空声称算出了结果。\n"
            "2. 用户提到某图层时，用下面列表里的 id 调用工具。\n"
            "3. 工具返回 new_layer_id 时，向用户说明新图层已生成。\n"
            f"\n当前可用图层：\n{lines}"
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
