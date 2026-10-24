#!/usr/bin/env python3
"""Write orchestrator/vllm_defaults.json: every field default of the vLLM config objects the
server log prints whole, read from vLLM's own source at VLLM_REF.

vLLM's `non-default args` line prints a config object passed as an argument whole, defaults
included (`'attention_config': AttentionConfig(backend=None, …, indexer_kv_dtype='auto', …)`).
A field printed at its default isn't something the run asked for, so the extractor must know
each default. They come from vLLM's dataclasses, never from this repo:

    python3 orchestrator/ingest/gen_vllm_defaults.py --ref v0.31.0

reads vllm/config/*.py at that tag (GitHub API, or --src DIR for a local checkout) and writes,
per dotted path (`attention_config.indexer_kv_dtype`), the literal default. A default that
isn't a literal (a factory, an env lookup) is recorded as {"unliteral": "<source>"}: such a
field is a request whenever it's printed, so the extractor can't mistake it for a default.
"""
from __future__ import annotations

import argparse
import ast
import base64
import json
import subprocess
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "vllm_defaults.json"

# Config objects the server log prints as an argument, by the arg name vLLM uses, and the
# module + class that defines each (nested objects are followed through their annotations).
ROOTS = {
    "attention_config": ("attention", "AttentionConfig"),
    "kernel_config": ("kernel", "KernelConfig"),
    "compilation_config": ("compilation", "CompilationConfig"),
    "engram_config": ("engram", "EngramConfig"),
    "speculative_config": ("speculative", "SpeculativeConfig"),
    "kv_transfer_config": ("kv_transfer", "KVTransferConfig"),
    "structured_outputs_config": ("structured_outputs", "StructuredOutputsConfig"),
    "observability_config": ("observability", "ObservabilityConfig"),
    "aux_output_config": ("aux_output", "AuxOutputConfig"),
}


def _source(ref: str, module: str, src: Path | None) -> str:
    """vllm/config/<module>.py, or vllm/<module>.py for a module given as a path."""
    rel = f"vllm/{module}.py" if "/" in module else f"vllm/config/{module}.py"
    if src:
        return (src / rel).read_text()
    out = subprocess.run(["gh", "api", f"repos/vllm-project/vllm/contents/{rel}?ref={ref}",
                          "--jq", ".content"], capture_output=True, text=True, check=True)
    return base64.b64decode(out.stdout).decode()


# The config classes EngineArgs' defaults refer to (`max_num_seqs: int | None =
# SchedulerConfig.max_num_seqs`), and their modules.
CONFIG_MODULES = {
    "ModelConfig": "model", "CacheConfig": "cache", "ParallelConfig": "parallel",
    "SchedulerConfig": "scheduler", "LoadConfig": "load", "KernelConfig": "kernel",
    "AttentionConfig": "attention", "CompilationConfig": "compilation", "SpeculativeConfig": "speculative",
}


def _default(node: ast.expr):
    """(literal value, True) or (source text, False)."""
    try:
        return ast.literal_eval(node), True
    except (ValueError, SyntaxError):
        pass
    if isinstance(node, ast.Call):
        kw = {k.arg: k.value for k in node.keywords}
        if "default" in kw:
            return _default(kw["default"])
        fac = kw.get("default_factory")
        if isinstance(fac, ast.Name) and fac.id in ("list", "dict", "set", "tuple"):
            return {"list": [], "dict": {}, "set": [], "tuple": []}[fac.id], True
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        # An enum member default, e.g. DynamicShapesType.BACKED: printed as its member name.
        return node.attr, True
    return ast.unparse(node), False


def _classes(tree: ast.Module) -> dict:
    return {c.name: c for c in tree.body if isinstance(c, ast.ClassDef)}


def walk(ref: str, src: Path | None) -> dict:
    trees, out = {}, {}

    def classes_of(module):
        if module not in trees:
            trees[module] = _classes(ast.parse(_source(ref, module, src)))
        return trees[module]

    def visit(prefix, module, cls_name, depth=0):
        cls = classes_of(module).get(cls_name)
        if cls is None or depth > 3:
            return
        for s in cls.body:
            if not (isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)):
                continue
            name = s.target.id
            if name.startswith("_"):
                continue
            path = f"{prefix}.{name}"
            ann = ast.unparse(s.annotation)
            # A nested config object (a class with annotated fields), not an enum type.
            nested = next((c for c, node in classes_of(module).items()
                           if c != cls_name and ann.split("|")[0].strip() == c
                           and any(isinstance(b, ast.AnnAssign) for b in node.body)
                           and not any(ast.unparse(base).endswith("Enum") for base in node.bases)), None)
            if nested:
                visit(path, module, nested, depth + 1)
                continue
            if s.value is None:
                out[path] = {"unliteral": "<required>"}
                continue
            v, ok = _default(s.value)
            out[path] = v if ok else {"unliteral": v}

    for arg, (module, cls) in sorted(ROOTS.items()):
        visit(arg, module, cls)

    # Top-level args: EngineArgs' own field defaults, following `Config.field` references.
    def field_default(cls_name, field_name):
        mod = CONFIG_MODULES.get(cls_name)
        cls = classes_of(mod).get(cls_name) if mod else None
        for s in (cls.body if cls else []):
            if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name) and s.target.id == field_name:
                return _default(s.value) if s.value is not None else ("<required>", False)
        return (f"{cls_name}.{field_name}", False)

    ea = classes_of("engine/arg_utils")["EngineArgs"]
    for s in ea.body:
        if not (isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)) or s.value is None:
            continue
        name = s.target.id
        if name.startswith("_") or name in ROOTS:
            continue
        v = s.value
        if isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name) and v.value.id in CONFIG_MODULES:
            d, ok = field_default(v.value.id, v.attr)
        elif isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name) and v.value.id.endswith("Config"):
            # A config class this table doesn't read: no default known, so any value is a request.
            d, ok = ast.unparse(v), False
        else:
            d, ok = _default(v)
        out[name] = d if ok else {"unliteral": d}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", required=True)
    ap.add_argument("--src", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=OUT)
    a = ap.parse_args(argv)
    doc = {"vllm_ref": a.ref, "defaults": walk(a.ref, a.src)}
    a.out.write_text(json.dumps(doc, indent=1, sort_keys=True, default=str) + "\n")
    print(f"wrote {a.out}: {len(doc['defaults'])} fields at {a.ref}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
