"""Generates multi-height-2d-temperature.png: a MOCK-UP (illustrative values).

Run from the repo root: python docs/mockups/multi_height_2d_temperature.py
"""

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle
from scipy.interpolate import RBFInterpolator

# Latest temperature (deg C) per wire, heights H1 (top) .. H5 (bottom).
# Positions are schematic: the real layout is unknown (sensors a few metres apart).
wires = {
    "WS_01_02": ((4.0, 3.0), [27.4, 26.8, 26.1, 25.3, 24.6]),
    "WS_01_03": ((9.0, 4.5), [28.1, 27.3, 26.6, 25.8, 25.0]),
    "WS_01_04": ((6.5, 9.0), [26.2, 25.7, 25.1, 24.5, 23.9]),
}
W, H, SEL = 14, 12, 2  # greenhouse extent (m), height layer shown in plan (H3)
pts = np.array([p for p, _ in wires.values()])
cmap, vmin, vmax = "RdYlBu_r", 23.5, 28.5


def field(h, xs, ys):
    vals = np.array([v[h] for _, v in wires.values()])
    f = RBFInterpolator(pts, vals, kernel="linear")
    return f(np.stack([xs.ravel(), ys.ravel()], 1)).reshape(xs.shape)


fig = plt.figure(figsize=(15, 7.5), facecolor="white")
gs = fig.add_gridspec(1, 2, width_ratios=[1.25, 1], wspace=0.18)

# Plan view
ax = fig.add_subplot(gs[0])
xs, ys = np.meshgrid(np.linspace(0, W, 200), np.linspace(0, H, 170))
z = field(SEL, xs, ys)
im = ax.imshow(z, extent=[0, W, H, 0], cmap=cmap, vmin=vmin, vmax=vmax, alpha=0.9)
ax.contour(xs, ys, z, levels=np.arange(23.5, 29, 0.5), colors="k", linewidths=0.4, alpha=0.35)
ax.add_patch(Rectangle((0, 0), W, H, fill=False, lw=2.5, ec="#374151"))
for name, ((x, y), v) in wires.items():
    ax.add_patch(
        FancyBboxPatch(
            (x - 0.75, y - 1.35), 1.5, 2.7,
            boxstyle="round,pad=0.05,rounding_size=.3",
            fc="white", ec="#111827", lw=1.6, zorder=5,
        )
    )
    for i, t in enumerate(v):
        yy = y - 1.05 + i * 0.525
        ax.text(x, yy, f"{t:.1f}", ha="center", va="center", fontsize=8.5, zorder=6,
                weight="bold" if i == SEL else "normal",
                color="#b91c1c" if i == SEL else "#111827")
        ax.text(x - 0.62, yy, f"H{i + 1}", ha="left", va="center", fontsize=5.5,
                color="#6b7280", zorder=6)
    ax.text(x, y - 1.6, name, ha="center", va="bottom", fontsize=9, weight="bold", zorder=6)
ax.set_xlim(0, W)
ax.set_ylim(H, 0)
ax.set_aspect("equal")
ax.set_xlabel("metres (schematic - real positions unknown)")
ax.set_ylabel("metres")
ax.set_title(f"Plan view - interpolated temperature at H{SEL + 1} (bold = layer shown)",
             loc="left", fontsize=12)
cb = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
cb.set_label(r"Temperature ($^\circ$C)")

# Side section through all wires, ordered by x
ax2 = fig.add_subplot(gs[1])
order = sorted(wires.items(), key=lambda kv: kv[1][0][0])
px = np.array([p[0] for _, (p, _) in order])
pv = np.array([v for _, (_, v) in order])
hx = np.linspace(px.min() - 1.5, px.max() + 1.5, 120)
hy = np.linspace(0, 4, 100)
sec = np.empty((len(hy), len(hx)))
for j, x in enumerate(hx):
    col = [np.interp(x, px, pv[:, k]) for k in range(5)]
    sec[:, j] = np.interp(hy, np.arange(5), col)
ax2.imshow(sec, extent=[hx[0], hx[-1], 4.5, -0.5], aspect="auto", cmap=cmap, vmin=vmin, vmax=vmax)
for name, ((x, _), v) in order:
    ax2.plot([x] * 5, range(5), color="#111827", lw=1)
    for i, t in enumerate(v):
        ax2.text(x, i, f"{t:.1f}", ha="center", va="center", fontsize=8, zorder=6,
                 bbox=dict(boxstyle="round,pad=.25", fc="white", ec="#111827", lw=0.8))
    ax2.text(x, -0.62, name, ha="center", va="bottom", fontsize=8.5, weight="bold")
ax2.set_yticks(range(5))
ax2.set_yticklabels([f"H{i + 1}" for i in range(5)])
ax2.set_ylim(4.5, -0.5)
ax2.set_xlabel("position along section (m)")
ax2.set_title("Side section - all heights (H1 top, H5 bottom)", loc="left", fontsize=12, pad=24)

fig.suptitle("Greenhouse temperature - latest reading from all multi-height wires "
             "(MOCK-UP, illustrative values)", fontsize=14, weight="bold", y=0.99)
fig.text(0.01, 0.01,
         "Boxes show the latest value per height. Colour between sensors is interpolated "
         "(linear RBF in plan; linear in x and height in section). "
         "The real UI would add an H1-H5 selector for the plan view.",
         fontsize=8, color="#4b5563")
fig.savefig("docs/mockups/multi-height-2d-temperature.png", dpi=130, bbox_inches="tight")
