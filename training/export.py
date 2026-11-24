"""Export a trained network to ONNX with its model card (model.json)."""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path
from typing import Any

import torch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from stage.separation.ssep.model import SsepNet, count_parameters  # noqa: E402

OPSET = 17


def export_onnx(net: SsepNet, out_dir: str | Path, training: dict[str, Any] | None = None,
                evaluation: dict[str, Any] | None = None, fp16: bool = False) -> Path:
    """Write model.onnx and model.json into `out_dir`; return the folder.

    The graph takes the spectrum and the waveform with dynamic batch and length. `fp16` halves
    the file by storing the weights in half precision (the CPU graph still computes in float32).
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    net = net.eval().float()
    c = net.cfg
    t = 64
    spec = torch.randn(1, 4, c.n_bins, t)
    wave = torch.randn(1, 2, (t - 1) * c.hop)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        torch.onnx.export(net, (spec, wave), str(out / "model.onnx"),
                          input_names=["spec", "wave"], output_names=["mask", "resid"],
                          dynamic_axes={"spec": {0: "batch", 3: "frames"},
                                        "wave": {0: "batch", 2: "samples"},
                                        "mask": {0: "batch", 4: "frames"},
                                        "resid": {0: "batch", 3: "samples"}},
                          opset_version=OPSET, dynamo=False)
    if fp16:
        import onnx
        from onnx import numpy_helper

        model = onnx.load(str(out / "model.onnx"))
        # Store large initialisers as float16 behind a Cast, so the arithmetic stays float32.
        nodes, inits = [], []
        for init in model.graph.initializer:
            arr = numpy_helper.to_array(init)
            if arr.dtype.name == "float32" and arr.size >= 1024:
                half = numpy_helper.from_array(arr.astype("float16"), init.name + "_fp16")
                inits.append(half)
                nodes.append(onnx.helper.make_node("Cast", [half.name], [init.name],
                                                   to=onnx.TensorProto.FLOAT))
            else:
                inits.append(init)
        del model.graph.initializer[:]
        model.graph.initializer.extend(inits)
        for node in reversed(nodes):
            model.graph.node.insert(0, node)
        onnx.save(model, str(out / "model.onnx"))
    card = {"config": json.loads(c.to_json()), "parameters": count_parameters(net),
            "onnx_opset": OPSET, "weights_dtype": "float16" if fp16 else "float32",
            "bytes": (out / "model.onnx").stat().st_size, "training": training or {},
            "evaluation": evaluation or {}}
    (out / "model.json").write_text(json.dumps(card, indent=2), encoding="utf-8")
    return out
