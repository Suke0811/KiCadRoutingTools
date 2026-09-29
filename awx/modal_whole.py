#!/usr/bin/env python3
"""Modal app: the WHOLE ROUTE's K ladder (whole_route.py), one container per rung.

    modal run awx/modal_whole.py::main --ks 15,28,35,41,51 --out DIR   (::main: the app has two entrypoints)

Each rung runs whole_route.py (the fanout on the whole route's ends, the solve, the loop, the route, the checks) in
its own container and sends back its log and its routed board, written to DIR/kK.log and DIR/kK_seq.kicad_pcb, so a
cloud ladder can be held against the laptop's copper for copper. The stack is the LAPTOP's: its Python (3.14) and
the same pinned numpy / scipy / shapely / ortools (modal_k.py: a python or numpy change moves routed copper). The
working tree is shipped as it stands, uncommitted edits and all.
"""
from __future__ import annotations

import io
import os
import subprocess
import tarfile
import time
from pathlib import Path

import modal

REPO = "/opt/krt"
_src = Path(__file__).resolve().parents[1]
PY_VERSION = os.environ.get("MODAL_WHOLE_PY", "3.14")
PINS = ("numpy==2.3.3", "scipy==1.16.2", "shapely==2.1.2", "ortools==9.15.6755")

image = (
    modal.Image.debian_slim(python_version=PY_VERSION)
    .apt_install("curl", "procps", "build-essential", "zsh")
    .pip_install(*PINS)
    .run_commands("curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal")
    .add_local_dir(str(_src), REPO, copy=True, ignore=[
        "**/.git/**", "**/__pycache__/**", "**/target/**",
        "**/.claude/worktrees/**", "**/tmp/**",
        # the local .so is macOS arm64 and would shadow the linux build
        "**/*.so", "**/*.dylib",
    ])
    .run_commands(
        f"cd {REPO} && (python3 build_router.py"
        f" || (. $HOME/.cargo/env && python3 build_router.py --from-source))",
        f"cd {REPO}/py_router && python3 -c \"import obstacle_map, grid_router;"
        f" print('grid_router', grid_router.__version__)\"",
        f"cd {REPO}/awx && python3 -c \"import fanout_from_plan, whole_solve;"
        f" print('awx imports ok')\"",
    )
)

app = modal.App("bus622-whole-ladder", image=image)


@app.function(cpu=(0.125, 4), memory=(256, 8192), timeout=14400, max_containers=20)
def run_rung(K: int, rounds: int = 3) -> dict:
    """One rung of the whole route, graded; its log and its routed board back."""
    wd = f"{REPO}/awx"
    out = f"/tmp/whole_k{K}"
    t0 = time.time()
    p = subprocess.run(["python3", "whole_route.py", str(K), out, str(rounds)], cwd=wd,
                       capture_output=True, text=True, errors="replace")
    board = ""
    for r in range(rounds, 0, -1):
        f = Path(out) / f"r{r}" / "seq.kicad_pcb"
        if f.exists():
            board = f.read_text(errors="replace")
            break
    # every stage's output beside the board (the fanout's intermediate source boards aside), to find where two machines part
    tb = io.BytesIO()
    with tarfile.open(fileobj=tb, mode="w:gz") as t:
        t.add(out, arcname=f"k{K}", filter=lambda ti: None if "_srcres" in ti.name else ti)
    cpu = subprocess.run(["sh", "-c", "grep -m1 'model name' /proc/cpuinfo"], capture_output=True, text=True).stdout
    return {"K": K, "rc": p.returncode, "secs": round(time.time() - t0), "log": p.stdout + p.stderr,
            "board": board, "cpu": cpu.strip(), "tgz": tb.getvalue()}


@app.local_entrypoint()
def main(ks: str = "15,28,35,41,51", out: str = "modal_whole_out", rounds: int = 3):
    d = Path(out)
    d.mkdir(parents=True, exist_ok=True)
    Ks = [int(k) for k in ks.split(",") if k]
    for res in run_rung.map(Ks, kwargs={"rounds": rounds}):
        K = res["K"]
        (d / f"k{K}.log").write_text(res["log"])
        if res["board"]:
            (d / f"k{K}_seq.kicad_pcb").write_text(res["board"])
        if res.get("tgz"):
            (d / f"k{K}_run.tgz").write_bytes(res["tgz"])
        grade = next((ln for ln in reversed(res["log"].splitlines()) if ln.startswith("WHOLE ")), "(no grade)")
        print(f"K{K}: rc {res['rc']}, {res['secs']} s on {res['cpu'][:60]} -- {grade}", flush=True)


@app.function(cpu=(0.125, 4), memory=(256, 8192), timeout=14400)
def run_stage(cmd: str, env: dict, tgz: bytes, outs: list) -> dict:
    """One command in the image on files shipped from the laptop AT THEIR OWN ABSOLUTE PATHS (a stage's JSON names the
    files it read), `outs` sent back the same way: a stage the two machines disagree on, replayed from the same bytes"""
    with tarfile.open(fileobj=io.BytesIO(tgz), mode="r:gz") as t:
        t.extractall("/", filter="fully_trusted")
    for o in outs:
        os.makedirs(os.path.dirname(o), exist_ok=True)
    p = subprocess.run(["zsh", "-c", cmd], cwd=f"{REPO}/awx", env=dict(os.environ, **env),
                       capture_output=True, text=True, errors="replace")
    ob = io.BytesIO()
    with tarfile.open(fileobj=ob, mode="w:gz") as t:
        for o in outs:
            if os.path.exists(o):
                t.add(o, arcname=o.lstrip("/"))
    return {"rc": p.returncode, "log": p.stdout + p.stderr, "tgz": ob.getvalue()}


@app.local_entrypoint()
def stage(cmd: str, ins: str, outs: str, env: str = "", into: str = "modal_stage_out"):
    """modal run awx/modal_whole.py::stage --cmd '...' --ins a,b --outs c,d [--env K=V;K=V] [--into DIR]: `ins` (files or
    directories, absolute) go up at their own paths, `outs` (absolute) come back under DIR at theirs"""
    tb = io.BytesIO()
    with tarfile.open(fileobj=tb, mode="w:gz") as t:
        for f in [x for x in ins.split(",") if x]:
            t.add(f, arcname=os.path.abspath(f).lstrip("/"))
    E = dict(kv.split("=", 1) for kv in env.split(";") if kv)
    res = run_stage.remote(cmd, E, tb.getvalue(), [x for x in outs.split(",") if x])
    Path(into).mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(res["tgz"]), mode="r:gz") as t:
        t.extractall(into, filter="data")
    (Path(into) / "stage.log").write_text(res["log"])
    print(f"rc {res['rc']}; outputs under {into}; log {into}/stage.log", flush=True)
