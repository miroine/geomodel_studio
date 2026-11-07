"""Synthetic demo project (no real field data): anticline with two faults, an erosional unconformity
and five wells whose tops are deliberately a little off the uncalibrated model."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .surface import Geometry, synthetic_surface
from .faults import Fault, next_color
from .project import Project
from .workflow import run_workflow
from .cpgrid import ZoneSpec
from .polygons import Polygon
from .wells import Well, wells_from_tops
from . import filters as flt


def build_demo() -> Project:
    x0, y0 = 450000.0, 6700000.0
    lat = Geometry(x0, y0, 100.0, 100.0, 81, 61, 0.0)
    p = Project(name="Demo anticline (synthetic)", lattice=lat)

    def put(s):
        p.put_surface(s)

    put(synthetic_surface(lat, "Top_Overburden", "tilted", z0=1500, dip_x=6, dip_y=-3, noise=2.5, seed=3))
    put(synthetic_surface(lat, "BCU", "tilted", z0=1900, dip_x=-8, dip_y=4, noise=3.0, seed=5))
    put(synthetic_surface(lat, "Top_Reservoir", "anticline", z0=2100, relief=300, width_x=1700, width_y=1300,
                          azimuth=35, dip_x=10, noise=2.0, seed=7))
    put(synthetic_surface(lat, "Isochore_Res", "anticline", z0=150, relief=55, width_x=1900, width_y=1500,
                          azimuth=35, noise=1.0, seed=9))

    # acquisition artefacts on the overburden map: spikes and a bad edge, to be cleaned by the filter stack
    rng0 = np.random.default_rng(21)
    ov = p.surfaces["Top_Overburden"].z.copy()
    idx = rng0.choice(ov.size, 25, replace=False)
    ov.flat[idx] += rng0.choice([-1, 1], 25) * rng0.uniform(60, 140, 25)
    p.put_surface(type(p.surfaces["Top_Overburden"])("Top_Overburden", lat, ov, "synthetic + spikes"))

    cx, cy = x0 + 4000, y0 + 3000
    f1 = Fault("F1_main", [[x0 - 400, y0 - 500], [x0 + 1500, y0 + 900], [x0 + 3300, y0 + 2400], [x0 + 5000, y0 + 3900], [x0 + 6500, y0 + 5300], [x0 + 8300, y0 + 6500]],
               ftype="normal", throw=70, dip=65, hw_side="left", profile="elliptical", drag=300, zref=2050,
               color=next_color(0))
    f2 = Fault("F2_antithetic", [[cx + 1200, cy - 2300], [cx + 1600, cy - 900], [cx + 2300, cy + 300]],
               ftype="normal", throw=35, dip=60, hw_side="right", profile="elliptical", drag=250, zref=2050,
               color=next_color(1))
    p.faults = {f.name: f for f in (f1, f2)}

    base_steps = [
        dict(type="faults", faults=["F1_main", "F2_antithetic"]),
        dict(type="surface", horizon="Top_Overburden", surface="Top_Overburden", shift=0.0, role="conformable"),
        dict(type="surface", horizon="BCU", surface="BCU", shift=0.0, role="erosional"),
        dict(type="surface", horizon="Top_Reservoir", surface="Top_Reservoir", shift=0.0, role="conformable"),
    ]
    iso = [
        dict(type="isochore", horizon="Mid_Reservoir", ref="Top_Reservoir", direction="below", mode="constant",
             thickness=60.0, gx=0.0, gy=0.0, role="conformable"),
        dict(type="isochore", horizon="Base_Reservoir", ref="Top_Reservoir", direction="below", mode="map",
             surface="Isochore_Res", role="conformable"),
        dict(type="isochore", horizon="Model_Base", ref="Base_Reservoir", direction="below", mode="constant",
             thickness=150.0, gx=0.0, gy=0.0, role="conformable"),
    ]
    # build an uncalibrated model to fabricate "observed" tops
    st0 = run_workflow(base_steps + iso, p.surfaces, p.faults, None, lat)
    wells = {"W-1": (cx - 2300, cy + 300), "W-2": (cx - 900, cy + 1900), "W-3": (cx + 300, cy - 1700),
             "W-4": (cx + 1500, cy + 1300), "W-5": (cx + 900, cy - 1000)}
    rng = np.random.default_rng(11)
    rows = []
    for w, (x, y) in wells.items():
        for h in ("Top_Reservoir", "Base_Reservoir"):
            zm = float(st0.depth_at(h, x, y)[0])
            bias = 14.0 * np.sin((x - x0) / 2600.0) + 8.0 * np.cos((y - y0) / 2100.0) + rng.normal(0, 1.0)
            rows.append(dict(well=w, x=x, y=y, horizon=h, z=round(zm + bias, 1)))
    p.tops = pd.DataFrame(rows)

    p.steps = (base_steps[:4]
               + [dict(type="calibrate", horizon="Top_Reservoir", label="Top_Reservoir", method="min_curvature",
                       radius=3500.0, tension=0.3, smoothing=0.0)]
               + iso
               + [dict(type="calibrate", horizon="Base_Reservoir", label="Base_Reservoir", method="min_curvature",
                       radius=3500.0, tension=0.3, smoothing=0.0)]
               + [dict(base_steps[0])])
    p.zones = [
        ZoneSpec("Overburden", "Top_Overburden", "BCU", nlayers=4, style="proportional", poro=0.10, permx=1, ntg=0.1),
        ZoneSpec("Cap", "BCU", "Top_Reservoir", nlayers=3, style="follow_base", dz=25.0, poro=0.12, permx=5, ntg=0.3),
        ZoneSpec("Res_Upper", "Top_Reservoir", "Mid_Reservoir", nlayers=6, style="proportional", poro=0.24, permx=450, ntg=0.9),
        ZoneSpec("Res_Lower", "Mid_Reservoir", "Base_Reservoir", nlayers=8, style="proportional", poro=0.19, permx=120, ntg=0.8),
        ZoneSpec("Underburden", "Base_Reservoir", "Model_Base", nlayers=4, style="proportional", poro=0.08, permx=0.5, ntg=0.2),
    ]
    p.grid_params = dict(dx=200.0, dy=200.0, min_thickness=0.1)

    # model boundary: an irregular licence-like outline inside the lattice
    xe, ye = x0 + 8000.0, y0 + 6000.0
    p.polygons["Boundary"] = Polygon("Boundary", [[x0 + 300, y0 + 400], [x0 + 5200, y0 + 100], [xe - 200, y0 + 1500],
                                                  [xe - 100, ye - 900], [x0 + 5600, ye - 150], [x0 + 800, ye - 300], [x0 + 150, y0 + 3000]])
    p.boundary = "Boundary"
    p.commit_filter("Top_Overburden", [flt.default_op("spikes", window=3, k=4.0), flt.default_op("fill", max_cells=2)])
    p.filter_presets["Clean spikes"] = [flt.default_op("spikes", window=3, k=4.0), flt.default_op("fill", max_cells=2)]
    p.wells = wells_from_tops(p.tops, {}, pad=350.0)
    p.wells["W-6"] = Well("W-6", cx - 1500, cy - 600, kb=25.0, td=2900.0,
                          survey=[[0, 0, 0], [900, 0, 0], [1400, 18, 60], [2000, 35, 70], [2900, 42, 75]], color="#F46036")
    return p
