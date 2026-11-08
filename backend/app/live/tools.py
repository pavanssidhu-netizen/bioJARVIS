"""Gemini Live tool relay. Kept as a thin facade: all tools are Skills in orchestration/skills.py."""
from __future__ import annotations

from typing import Any

from ..contracts import ToolCallIn
from ..orchestration import skills
from ..services.store import Store

OBS_TYPES = skills.OBS_TYPES


def tool_declarations() -> list[dict[str, Any]]:
    return skills.live_declarations()


TOOL_DECLARATIONS = tool_declarations()
TOOL_NAMES = skills.tool_names()


async def execute_tool(store: Store, call: ToolCallIn) -> dict[str, Any]:
    ctx = skills.SkillContext(store=store, experiment_id=call.experiment_id, session_id=call.session_id,
                              call_id=call.call_id, image_base64=call.image_base64)
    return await skills.execute(call.name, ctx, call.args)
