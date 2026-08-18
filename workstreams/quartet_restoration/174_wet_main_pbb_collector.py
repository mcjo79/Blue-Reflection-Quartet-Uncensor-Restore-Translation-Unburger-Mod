#!/usr/bin/env python3
"""Read-only qrenderdoc collector for the accepted main-PBB draw.

Open an Original or Quartet RDC in qrenderdoc, select the already-identified
main-PBB draw in Event Browser, set BR_WET_EDITION and BR_WET_OUTPUT, then run
this file from Tools -> Python Shell.  The script exports only the one selected
draw's fixed-function state and fragment/pixel-shader identity.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import renderdoc as rd


def value(obj, name, default=None):
    try:
        return getattr(obj, name)
    except Exception:
        return default


def scalar(obj):
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    return str(obj)


def fields(obj, names):
    return {name: scalar(value(obj, name)) for name in names if value(obj, name) is not None}


def blend_equation(obj):
    return fields(obj, ("source", "destination", "operation"))


def stencil_face(obj):
    return fields(obj, (
        "failOperation", "depthFailOperation", "passOperation", "function",
        "reference", "compareMask", "writeMask",
    ))


def collect(controller):
    edition = os.environ.get("BR_WET_EDITION", "").strip().casefold()
    output_text = os.environ.get("BR_WET_OUTPUT", "").strip()
    if edition not in ("original", "quartet"):
        raise RuntimeError("BR_WET_EDITION must be 'original' or 'quartet'")
    if not output_text:
        raise RuntimeError("BR_WET_OUTPUT must name the JSON output file")
    if not pyrenderdoc.IsCaptureLoaded():
        raise RuntimeError("open an RDC capture before running the collector")

    event_id = int(pyrenderdoc.CurEvent())
    action = controller.GetAction(event_id)
    if action is None:
        raise RuntimeError("select the accepted main-PBB draw in Event Browser")
    pipe = controller.GetPipelineState()
    if pipe is None:
        raise RuntimeError("selected event has no graphics pipeline state")

    stage = rd.ShaderStage.Pixel
    shader_id = pipe.GetShader(stage)
    entry = pipe.GetShaderEntryPoint(stage)
    reflection = pipe.GetShaderReflection(stage)
    disassembly = ""
    if reflection is not None:
        disassembly = controller.DisassembleShader(pipe.GetGraphicsPipelineObject(), reflection, "")
    disassembly_bytes = disassembly.encode("utf-8", errors="replace")

    blends = []
    for blend in pipe.GetColorBlends():
        row = fields(blend, (
            "enabled", "logicOperationEnabled", "logicOperation", "writeMask",
        ))
        row["colorBlend"] = blend_equation(value(blend, "colorBlend"))
        row["alphaBlend"] = blend_equation(value(blend, "alphaBlend"))
        blends.append(row)
    depth = fields(pipe.GetDepthTestState(), (
        "depthEnable", "depthWrites", "depthFunction", "depthBounds",
        "minDepthBounds", "maxDepthBounds",
    ))
    stencil_pair = pipe.GetStencilFaces()
    try:
        stencil_items = list(stencil_pair)
    except Exception:
        stencil_items = [value(stencil_pair, "first"), value(stencil_pair, "second")]
    stencil = {
        "front": stencil_face(stencil_items[0]) if len(stencil_items) > 0 else {},
        "back": stencil_face(stencil_items[1]) if len(stencil_items) > 1 else {},
    }
    raster = fields(pipe.GetRasterState(), ("fillMode", "cullMode", "frontCCW"))

    record = {
        "schema_version": 1,
        "type": "br_wet_main_pbb_selected_draw_state",
        "edition": edition,
        "selection_contract": "user-selected accepted main-PBB draw only",
        "event_id": event_id,
        "action_name": str(value(action, "customName", "")),
        "action_flags": str(value(action, "flags", "")),
        "graphics_api": str(controller.GetAPIProperties().pipelineType),
        "graphics_pipeline_resource_id": str(pipe.GetGraphicsPipelineObject()),
        "fragment_or_pixel_shader_resource_id": str(shader_id),
        "fragment_or_pixel_shader_entry_point": str(entry),
        "fragment_or_pixel_shader_disassembly_sha256": hashlib.sha256(disassembly_bytes).hexdigest(),
        "fragment_or_pixel_shader_disassembly_size": len(disassembly_bytes),
        "blend": {"factor": [float(item) for item in pipe.GetBlendFactor()], "targets": blends},
        "depth": depth,
        "stencil": stencil,
        "raster": raster,
        "captures_or_launches_game": False,
        "writes_process_memory": False,
        "edits_game_files": False,
    }
    output = Path(output_text).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, output)
    print("WET_MAIN_PBB_STATE=" + str(output))


pyrenderdoc.Replay().BlockInvoke(collect)
