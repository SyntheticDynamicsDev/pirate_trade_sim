import math
import random
from dataclasses import dataclass
import pygame

@dataclass
class WakeParticle:
    x: float
    y: float
    vx: float
    vy: float
    radius: float
    age: float
    life: float

    kind: str = "dot"       # "dot" | "stripe" | "bow"
    angle_deg: float = 0.0  # für "stripe"
    length: float = 0.0     # für "stripe"

class WakeSystem:
    def __init__(self) -> None:
        self._parts: list[WakeParticle] = []
        self._spawn_acc = 0.0
        self._bow_spawn_acc = 0.0


        # Tuning
        self.base_rate = 2.0          # Partikel/s (bei sehr wenig Speed)
        self.speed_rate = 0.10        # zusätzl. Partikel/s pro px/s Speed
        self.max_parts = 260

        self.behind_dist = 18.0       # hinter dem Schiff
        self.side_spread = 7.0        # seitliche Streuung

        self.min_life = 0.55
        self.max_life = 1.10
        self.min_radius = 2.0
        self.max_radius = 5.0

        # Heck-"Stripes" (längliche Spur)
        self.stripe_chance = 0.45
        self.min_stripe_len = 8.0
        self.max_stripe_len = 16.0
        self.stripe_width = 3.0

        # Bugwelle
        self.front_dist = 18.0          # vor dem Schiff
        self.bow_side = 10.0            # seitlich am Bug
        self.bow_rate = 0.55            # Partikel/s Basis (zusätzlich zu speed)
        self.bow_speed_rate = 0.015     # Partikel/s pro px/s Speed


    def update(self, dt: float, ship_pos: tuple[float, float], ship_vel: tuple[float, float]) -> None:
        # Partikel updaten
        for p in self._parts:
            p.age += dt
            p.x += p.vx * dt
            p.y += p.vy * dt

        # Tote entfernen
        self._parts = [p for p in self._parts if p.age < p.life]

        vx, vy = ship_vel
        speed = math.hypot(vx, vy)
        if speed < 5.0:
            return  # im Stand keine Wake

        # Spawnrate abhängig vom Speed
        rate = self.base_rate + speed * self.speed_rate  # particles/sec
        self._spawn_acc += rate * dt

        # Richtung (aus Velocity)
        inv = 1.0 / speed
        dx = vx * inv
        dy = vy * inv

        # Rechtsvektor (90°)
        rx = -dy
        ry = dx

        sx, sy = ship_pos

        while self._spawn_acc >= 1.0 and len(self._parts) < self.max_parts:
            self._spawn_acc -= 1.0

            side = (random.random() * 2.0 - 1.0) * self.side_spread
            px = sx - dx * self.behind_dist + rx * side
            py = sy - dy * self.behind_dist + ry * side

            back_speed = 20.0 + speed * 0.12
            pvx = -dx * back_speed + rx * (random.random() * 2.0 - 1.0) * 10.0
            pvy = -dy * back_speed + ry * (random.random() * 2.0 - 1.0) * 10.0

            life = random.uniform(self.min_life, self.max_life)

            # dot oder stripe
            if random.random() < self.stripe_chance:
                # stripe: kleiner gedrehter Strich entlang Fahrtrichtung
                length = random.uniform(self.min_stripe_len, self.max_stripe_len)
                radius = float(self.stripe_width)  # "radius" als width verwendet
                angle_deg = math.degrees(math.atan2(dy, dx))  # Richtung der Bewegung
                self._parts.append(
                    WakeParticle(px, py, pvx, pvy, radius, 0.0, life, kind="stripe", angle_deg=angle_deg, length=length)
                )
            else:
                radius = random.uniform(self.min_radius, self.max_radius)
                self._parts.append(
                    WakeParticle(px, py, pvx, pvy, radius, 0.0, life, kind="dot")
                )

        # -------------------------------
        # Bugwelle (links/rechts am Bug)
        # -------------------------------
        bow_rate = self.bow_rate + speed * self.bow_speed_rate
        self._bow_spawn_acc += bow_rate * dt

        while self._bow_spawn_acc >= 1.0 and len(self._parts) < self.max_parts:
            self._bow_spawn_acc -= 1.0

            # links oder rechts
            sign = -1.0 if random.random() < 0.5 else 1.0
            px = sx + dx * self.front_dist + rx * (sign * self.bow_side + (random.random() * 2.0 - 1.0) * 2.0)
            py = sy + dy * self.front_dist + ry * (sign * self.bow_side + (random.random() * 2.0 - 1.0) * 2.0)

            # Bugwelle driftet leicht nach außen + minimal nach hinten
            outward = 18.0 + speed * 0.06
            back = 10.0 + speed * 0.04
            pvx = rx * (sign * outward) - dx * back
            pvy = ry * (sign * outward) - dy * back

            life = random.uniform(0.35, 0.75)
            radius = random.uniform(2.0, 4.5)

            self._parts.append(
                WakeParticle(px, py, pvx, pvy, radius, 0.0, life, kind="bow")
            )

    def render(self, screen: "pygame.Surface") -> None:
        if not self._parts:
            return

        # Overlay für Alpha (perf. ausreichend für Stufe 1)
        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)

        for p in self._parts:
            t = p.age / p.life
            # Alpha fällt über Lebenszeit ab
            alpha = int(110 * (1.0 - t))
            if alpha <= 0:
                continue

            # leichtes “Auflösen” durch Radius-Wachstum
            r = p.radius * (1.0 + 0.55 * t)

            if p.kind in ("dot", "bow"):
                pygame.draw.circle(overlay, (235, 235, 235, alpha), (int(p.x), int(p.y)), int(r))
            else:
                # stripe: dünner, gedrehter Strich
                w = max(2, int(r))  # "r" als width
                h = max(4, int(p.length * (1.0 + 0.35 * t)))  # wächst leicht
                tmp = pygame.Surface((h, w), pygame.SRCALPHA)
                tmp.fill((235, 235, 235, alpha))
                rot = pygame.transform.rotozoom(tmp, -p.angle_deg, 1.0)
                rect = rot.get_rect(center=(int(p.x), int(p.y)))
                overlay.blit(rot, rect)


        screen.blit(overlay, (0, 0))
