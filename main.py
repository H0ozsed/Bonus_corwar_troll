#!/usr/bin/env python3
"""corewar_marble_refactored

A tidy, PEP‑8–compliant re‑write of *Corewar Marble*: a tiny Panda3D visualiser that
turns a Corewar execution log into a cute marble race.

Run with the path to your log file::

    python corewar_marble_refactored.py my_run.log

The log must contain lines such as::

    The player 1(foobar) is alive.
    The player 3(baz) has won.

Every *alive* line moves the corresponding marble forward; the *win* line paints
it gold and stops the replay.
"""

from __future__ import annotations

import sys
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Iterator, List

from direct.showbase.ShowBase import ShowBase  # type: ignore
from direct.task import Task                   # type: ignore
from panda3d.core import (                     # type: ignore
    AmbientLight,
    CardMaker,
    DirectionalLight,
    TextNode,
    Vec3,
    Vec4,
    WindowProperties,
)

# ---------------------------------------------------------------------------
# Configuration ‑‑ tweak at will ✨
# ---------------------------------------------------------------------------

LINE_TIME: float      = 0.4        # seconds per log line
STEP_DIST: float      = 4.0        # units advanced per *alive* ping
SPEED: float          = STEP_DIST / LINE_TIME  # auto‑derived marble speed

FLOOR_HALF: int       = 1_000      # half‑size of the grey floor (→ 2000×2000)
START_Y: int          = 0          # Y coordinate of the starting line
LANES_X: List[int]    = [-15, -5, 5, 15]  # 4 starting X positions for marbles

CAMERA_OFFSET: int    = 60         # camera sits 60 units behind the start
CAMERA_HEIGHT: int    = 35         # …and 35 units above the ground

FLY_SPEED: float      = 30         # normal free‑cam speed
SPRINT_FACTOR: int    = 2          # hold ⇧Shift to double that speed

MOUSE_SENSITIVITY: float = 0.16    # degrees per pixel

# ---------------------------------------------------------------------------
# Compiled regexen 🕵️‍♀️
# ---------------------------------------------------------------------------

R_ALIVE = re.compile(r"The player \d+\(([^)]+)\) is alive\.")
R_WIN   = re.compile(r"The player \d+\(([^)]+)\) has won\.")

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Player:
    """All the scene graph nodes that belong to a marble + its state."""

    model: "NodePath"  # the marble mesh
    label: "NodePath"  # billboarded text above the marble
    travelled: float = 0.0  # how far we have actually moved (Z)
    target: float    = 0.0  # how far we *should* be after the last tick

    def move(self, delta: float) -> None:
        """Move the marble *delta* units forward on Y."""
        self.travelled += delta
        self.model.set_y(self.model, delta)  # local‑axis move

# ---------------------------------------------------------------------------
# Main application 🍿
# ---------------------------------------------------------------------------

class CorewarMarble(ShowBase):
    """Panda3D application driving the marble animation."""

    _players: Dict[str, Player]
    _next_lane: int
    _log_lines: Iterator[str]

    def __init__(self, lines: Iterable[str]) -> None:  # noqa: D401
        super().__init__()

        # -- Window & free‑cam set‑up --------------------------------------
        props = WindowProperties()
        props.setCursorHidden(True)
        self.win.requestProperties(props)
        self.disableMouse()

        self._init_camera()
        self._bind_keys()

        # -- Scene: grey floor + lights ------------------------------------
        self._build_floor()
        self._setup_lighting()

        # -- State ----------------------------------------------------------
        self._players = {}
        self._next_lane = 0
        self._log_lines = self._clean(lines)

        # -- Task chain -----------------------------------------------------
        self.task_mgr.add(self._update_mouse, "🌈 mouse‑look")
        self.task_mgr.add(self._update_movement, "🚀 free‑cam‑move")
        self.task_mgr.add(self._lerp_marbles, "🐣 smooth‑marble‑motion")
        self.task_mgr.doMethodLater(LINE_TIME, self._tick_log, "📜 replay‑log")

    # ------------------------------------------------------------------
    # 🌟  Camera helpers
    # ------------------------------------------------------------------

    def _init_camera(self) -> None:
        """Position the free camera at the initial vantage point."""
        self.camera.set_pos(0, START_Y - CAMERA_OFFSET, CAMERA_HEIGHT)
        self.camera.look_at(0, START_Y, 0)

        self._heading: float = 0.0
        self._pitch: float = 0.0

        # store centre of the window for cursor warping
        self._cx = self.win.get_x_size() // 2
        self._cy = self.win.get_y_size() // 2
        self.win.movePointer(0, self._cx, self._cy)

    # Key‑handling -------------------------------------------------------

    def _bind_keys(self) -> None:
        self._keys = {k: False for k in "wasdqe"} | {"shift": False}

        for key in self._keys:
            self.accept(key,       self._set_key, [key, True])
            self.accept(f"{key}-up", self._set_key, [key, False])
        self.accept("escape", sys.exit)

    def _set_key(self, key: str, state: bool) -> None:
        self._keys[key] = state

    # Mouse‑look ---------------------------------------------------------

    def _update_mouse(self, task: Task) -> Task:
        md = self.win.getPointer(0)
        dx = md.get_x() - self._cx
        dy = md.get_y() - self._cy

        self._heading -= dx * MOUSE_SENSITIVITY
        self._pitch = max(-90, min(90, self._pitch - dy * MOUSE_SENSITIVITY))

        self.camera.set_hpr(self._heading, self._pitch, 0)
        self.win.movePointer(0, self._cx, self._cy)
        return Task.cont

    # Keyboard movement --------------------------------------------------

    def _update_movement(self, task: Task) -> Task:
        dt = globalClock.getDt()
        direction = Vec3(0)
        q = self.camera.getQuat()

        if self._keys["w"]:
            direction += q.getForward()
        if self._keys["s"]:
            direction -= q.getForward()
        if self._keys["a"]:
            direction -= q.getRight()
        if self._keys["d"]:
            direction += q.getRight()
        if self._keys["q"]:
            direction += q.getUp()
        if self._keys["e"]:
            direction -= q.getUp()

        if direction.length_squared() > 0:
            speed = FLY_SPEED * (SPRINT_FACTOR if self._keys["shift"] else 1)
            self.camera.set_pos(self.camera.get_pos() + direction.normalized() * speed * dt)
        return Task.cont

    # ------------------------------------------------------------------
    # 🌟  Scene helpers
    # ------------------------------------------------------------------

    def _build_floor(self) -> None:
        cm = CardMaker("floor")
        cm.setFrame(-FLOOR_HALF, FLOOR_HALF, -FLOOR_HALF, FLOOR_HALF)
        floor_np = self.render.attachNewNode(cm.generate())
        floor_np.set_p(-90)
        floor_np.set_color(0.5, 0.5, 0.5, 1)
        floor_np.set_two_sided(True)

    def _setup_lighting(self) -> None:
        ambient = AmbientLight("ambient")
        ambient.set_color(Vec4(0.45, 0.45, 0.45, 1))
        sun = DirectionalLight("sun")
        sun.set_color(Vec4(0.9, 0.9, 0.9, 1))
        self.render.set_light(self.render.attachNewNode(ambient))
        self.render.set_light(self.render.attachNewNode(sun))

    # ------------------------------------------------------------------
    # 🌟  Marble helpers
    # ------------------------------------------------------------------

    def _ensure_player(self, name: str) -> Player:
        """Return the *Player* instance, creating its visual nodes if needed."""
        if name in self._players:
            return self._players[name]

        lane_x = LANES_X[self._next_lane % len(LANES_X)]
        self._next_lane += 1

        # --- model ------------------------------------------------------
        ball = self.loader.loadModel("models/smiley")
        ball.set_scale(1.0)
        ball.set_pos(lane_x, START_Y, 1.5)
        ball.reparent_to(self.render)

        # --- name label --------------------------------------------------
        tn = TextNode(f"label‑{name}")
        tn.setText(name)
        tn.setAlign(TextNode.ACenter)
        label_np = ball.attachNewNode(tn)
        label_np.set_scale(0.8)
        label_np.set_pos(0, 0, 1.8)
        label_np.set_billboard_axis()

        player = Player(model=ball, label=label_np)
        self._players[name] = player
        return player

    # Smooth interpolation ---------------------------------------------

    def _lerp_marbles(self, task: Task) -> Task:
        dt = globalClock.getDt()
        step = SPEED * dt
        for player in self._players.values():
            if player.travelled < player.target:
                remaining = player.target - player.travelled
                player.move(min(step, remaining))
        return Task.cont

    # ------------------------------------------------------------------
    # 🌟  Log playback
    # ------------------------------------------------------------------

    def _tick_log(self, task: Task) -> Task:
        try:
            line = next(self._log_lines)
        except StopIteration:
            return Task.done

        if match := R_ALIVE.match(line):
            name = match.group(1)
            player = self._ensure_player(name)
            player.target += STEP_DIST
        elif match := R_WIN.match(line):
            name = match.group(1)
            player = self._ensure_player(name)
            player.target += STEP_DIST
            player.model.set_color(Vec4(1, 0.84, 0, 1))  # gold 🏆
            print(f"🏆  {name} a gagné !")
            return Task.done

        return Task.again

    # ------------------------------------------------------------------
    # 🌟  Misc.
    # ------------------------------------------------------------------

    @staticmethod
    def _clean(lines: Iterable[str]) -> Iterator[str]:
        """Return an iterator of non‑blank, stripped lines."""
        return (l.strip() for l in lines if l.strip())


# ---------------------------------------------------------------------------
# Entrypoint 🚪
# ---------------------------------------------------------------------------


def main() -> None:  # noqa: D401
    if len(sys.argv) != 2:
        sys.exit("Usage: python corewar_marble_refactored.py <log.txt>")

    log_path = Path(sys.argv[1])
    if not log_path.is_file():
        sys.exit(f"Fichier introuvable : {log_path}")

    with log_path.open(encoding="utf‑8") as fp:
        CorewarMarble(fp.readlines()).run()


if __name__ == "__main__":
    main()

