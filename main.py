#!/usr/bin/env python3
"""
corewar_marble_particles_safe.py
Visualise un log Corewar sous forme de course de billes.

Contrôles :
    W A S D / Q E  → déplacer la caméra
    ⇧ Shift        → sprinter la caméra
    P              → doubler la cadence du replay
    O              → diviser la cadence par 2
"""

from __future__ import annotations
import sys, re
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, List

from direct.showbase.ShowBase import ShowBase            # type: ignore
from direct.task import Task                             # type: ignore
from direct.particles.ParticleEffect import ParticleEffect  # type: ignore
from panda3d.core import (                               # type: ignore
    AmbientLight, CardMaker, DirectionalLight,
    TextNode, Vec3, Vec4, WindowProperties,
)

# ─── Configuration ────────────────────────────────────────────────────
LINE_DT    = 0.4
STEP_DIST  = 4.0
SPEED      = STEP_DIST / LINE_DT

FLOOR_HALF = 1_000
START_Y    = 0
LANES_X    = [-15, -5, 5, 15]

CAM_BACK   = 60
CAM_HGT    = 35
FLY_VEL    = 30
SPRINTx2   = 2
SENS       = 0.16

T_MIN, T_MAX = 0.05, 2.0   # bornes pour P/O

R_ALIVE = re.compile(r"The player \d+\(([^)]+)\) is alive\.")
R_WIN   = re.compile(r"The player \d+\(([^)]+)\) has won\.")

# ─── Dataclass Player ────────────────────────────────────────────────
@dataclass
class Player:
    model: "NodePath"
    label: "NodePath"
    travelled: float = 0.0
    target: float    = 0.0
    winner: bool     = False
    def move(self, d: float) -> None:
        self.travelled += d
        self.model.set_y(self.model, d)

# ─── Application class ───────────────────────────────────────────────
class CorewarMarble(ShowBase):
    def __init__(self, log_lines: Iterable[str]) -> None:
        super().__init__()

        # Window + mouse
        wp = WindowProperties(); wp.setCursorHidden(True)
        self.win.requestProperties(wp); self.disableMouse()
        self.h = self.p = 0.0
        self.cx, self.cy = self.win.getXSize()//2, self.win.getYSize()//2
        self.camera.set_pos(0, START_Y - CAM_BACK, CAM_HGT)
        self.camera.look_at(0, START_Y, 0)
        self.win.movePointer(0, self.cx, self.cy)

        # Keymap
        self.keys = {k: False for k in "wasdqe"} | {"shift": False}
        for k in self.keys:
            self.accept(k,        self._set_key, [k, True])
            self.accept(f"{k}-up", self._set_key, [k, False])
        self.accept("p", self._faster)
        self.accept("o", self._slower)
        self.accept("escape", sys.exit)

        # Floor
        cm = CardMaker("floor")
        cm.setFrame(-FLOOR_HALF, FLOOR_HALF, -FLOOR_HALF, FLOOR_HALF)
        floor = self.render.attachNewNode(cm.generate())
        floor.set_p(-90)
        floor.set_color(0.5, 0.5, 0.5, 1)
        floor.set_two_sided(True)

        # Lights
        amb = AmbientLight("amb");   amb.setColor(Vec4(0.45, 0.45, 0.45, 1))
        sun = DirectionalLight("sun"); sun.setDirection(Vec3(-1, -1, -2))
        sun.setColor(Vec4(0.9, 0.9, 0.9, 1))
        self.render.set_light(self.render.attachNewNode(amb))
        self.render.set_light(self.render.attachNewNode(sun))

        # State
        self.players: Dict[str, Player] = {}
        self.next_lane = 0
        self.lines: Iterator[str] = (l.strip() for l in log_lines if l.strip())
        self.tick_dt = LINE_DT

        # Tasks
        self.task_mgr.add(self._mouse_look, "mouse")
        self.task_mgr.add(self._free_move,  "move")
        self.task_mgr.add(self._lerp,       "lerp")
        self._schedule_tick()

    # ── Input helpers ────────────────────────────────────────────────
    def _set_key(self, k: str, v: bool) -> None: self.keys[k] = v

    def _mouse_look(self, t: Task) -> Task:
        md = self.win.getPointer(0)
        dx, dy = md.get_x() - self.cx, md.get_y() - self.cy
        self.h -= dx * SENS
        self.p = max(-90, min(90, self.p - dy * SENS))
        self.camera.set_hpr(self.h, self.p, 0)
        self.win.movePointer(0, self.cx, self.cy)
        return Task.cont

    def _free_move(self, t: Task) -> Task:
        dt, vec = globalClock.getDt(), Vec3(0)
        q = self.camera.getQuat()
        if self.keys["w"]: vec += q.getForward()
        if self.keys["s"]: vec -= q.getForward()
        if self.keys["a"]: vec -= q.getRight()
        if self.keys["d"]: vec += q.getRight()
        if self.keys["q"]: vec += q.getUp()
        if self.keys["e"]: vec -= q.getUp()
        if vec.length_squared():
            speed = FLY_VEL * (SPRINTx2 if self.keys["shift"] else 1)
            self.camera.set_pos(self.camera.get_pos() + vec.normalized()*speed*dt)
        return Task.cont

    # ── Marble logic ────────────────────────────────────────────────
    def _ensure_player(self, name: str) -> Player:
        if name in self.players:
            return self.players[name]
        lane_x = LANES_X[self.next_lane % len(LANES_X)]
        self.next_lane += 1
        ball = self.loader.loadModel("models/smiley")
        ball.set_scale(1); ball.set_pos(lane_x, START_Y, 1.5); ball.reparent_to(self.render)
        tn = TextNode(name); tn.setText(name); tn.setAlign(TextNode.ACenter)
        label = ball.attachNewNode(tn); label.set_scale(.8); label.set_pos(0,0,1.8); label.set_billboard_axis()
        pl = Player(ball, label); self.players[name] = pl; return pl

    def _lerp(self, t: Task) -> Task:
        dt, step = globalClock.getDt(), SPEED*globalClock.getDt()
        for pl in self.players.values():
            if not pl.winner and pl.travelled < pl.target:
                pl.move(min(step, pl.target - pl.travelled))
        return Task.cont

    # ── Particles (safe) ─────────────────────────────────────────────
    def _sparkle(self, pl: Player) -> None:
        fx = ParticleEffect()
        for preset in ("models/particles/sparkles.ptf",
                       "models/particles/sparkle.ptf",
                       "models/particles/firework.ptf"):
            try:
                fx.loadConfig(preset)
                fx.start(parent=pl.model, renderParent=self.render)
                return
            except OSError:
                continue
        print("⚠️  Pas de preset de particules trouvé ; bille simplement dorée.")

    # ── Log processing ──────────────────────────────────────────────
    def _schedule_tick(self) -> None:
        self.task_mgr.doMethodLater(self.tick_dt, self._tick_log, "log")

    def _tick_log(self, task: Task) -> Task:
        try: line = next(self.lines)
        except StopIteration: return Task.done

        if m := R_ALIVE.match(line):
            pl = self._ensure_player(m.group(1)); pl.target += STEP_DIST
        elif m := R_WIN.match(line):
            pl = self._ensure_player(m.group(1)); pl.target += STEP_DIST
            pl.winner = True; pl.model.set_color(Vec4(1,0.84,0,1)); self._sparkle(pl)
            print(f"🏆 {m.group(1)} a gagné !")
            return Task.done

        task.delayTime = self.tick_dt
        return Task.again

    # ── Speed control ───────────────────────────────────────────────
    def _faster(self) -> None:
        self.tick_dt = max(T_MIN, self.tick_dt / 2)
        print(f"⏩ Cadence : {self.tick_dt:.2f} s / ligne")

    def _slower(self) -> None:
        self.tick_dt = min(T_MAX, self.tick_dt * 2)
        print(f"⏪ Cadence : {self.tick_dt:.2f} s / ligne")

# ─── Entry point ────────────────────────────────────────────────────
def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Usage : python corewar_marble_particles_safe.py <log.txt>")
    log_path = Path(sys.argv[1])
    if not log_path.is_file():
        sys.exit(f"Fichier introuvable : {log_path}")
    with log_path.open(encoding="utf-8") as fp:
        CorewarMarble(fp.readlines()).run()

if __name__ == "__main__":
    main()

