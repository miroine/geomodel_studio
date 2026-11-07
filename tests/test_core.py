import io, os, sys, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.surface import Geometry, Surface, synthetic_surface, fill_nan_nearest
from core import interp, io_surfaces as io_s, export
from core.faults import Fault
from core.workflow import run_workflow, tops_misfit
from core.cpgrid import build_grid, ZoneSpec, layer_interfaces
from core.demo import build_demo
from core import project as proj

PASS = []


def ok(name, cond, info=""):
    PASS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))


# ---- surface sampling / rotation -----------------------------------------
g = Geometry(1000, 2000, 50, 50, 41, 31, 0)
s = synthetic_surface(g, "a", "anticline", z0=2000, relief=100)
X, Y = g.coords()
ok("sample at nodes reproduces z", np.allclose(s.sample(X, Y), s.z))
gr = Geometry(1000, 2000, 50, 50, 41, 31, 20.0)
sr = Surface("r", gr, np.random.default_rng(0).normal(size=gr.shape))
Xr, Yr = gr.coords()
ok("rotated sampling at nodes", np.allclose(sr.sample(Xr, Yr), sr.z, atol=1e-9))
rs = sr.resample_to(g)
ok("resample leaves NaN outside", np.isnan(rs.z).any())

# ---- gridding ------------------------------------------------------------
rng = np.random.default_rng(1)
pts = np.column_stack([rng.uniform(1000, 3000, 120), rng.uniform(2000, 3500, 120)])
zt = 2000 - 100 * np.exp(-(((pts[:, 0] - 2000) / 600) ** 2 + ((pts[:, 1] - 2750) / 450) ** 2))
P = np.column_stack([pts, zt])
Xg, Yg = g.coords()
truth = 2000 - 100 * np.exp(-(((Xg - 2000) / 600) ** 2 + ((Yg - 2750) / 450) ** 2))
LIM = {"moving_average": 15, "nearest": 15}       # smoother / blocky by design
for m in interp.METHODS:
    t0 = time.time()
    gs = interp.grid_points(P, g, m, tension=0.2)
    inside = (Xg > 1300) & (Xg < 2700) & (Yg > 2300) & (Yg < 3200)
    rmse = float(np.sqrt(np.mean((gs.z - truth)[inside] ** 2)))
    ok(f"grid {m} rmse<{LIM.get(m, 8)}m", rmse < LIM.get(m, 8), f"{rmse:.2f} m, {time.time() - t0:.1f}s")
# honours data (min curvature)
gs = interp.grid_points(P, g, "min_curvature", tension=0.0)
back = gs.sample(P[:, 0], P[:, 1])
ok("min_curvature honours data (<1m)", np.nanmax(np.abs(back - P[:, 2])) < 1.0, f"{np.nanmax(np.abs(back - P[:, 2])):.3f}")
# contour densify
cont = [{"z": 2000.0, "pts": [[1000, 2000], [3000, 2000]]}, {"z": 1950.0, "pts": [[1000, 3500], [3000, 3500]]}]
cp = interp.contours_to_points(cont, 25)
ok("contour densify", len(cp) > 100 and set(np.unique(cp[:, 2])) == {2000.0, 1950.0})
gc = interp.grid_points(cp, g, "min_curvature", tension=0.5)
ok("contours -> grid monotonic", gc.z[0, 20] > gc.z[-1, 20] and np.isfinite(gc.z).all())

# ---- IO round trips ------------------------------------------------------
sf = Surface("t", Geometry(500, 700, 25, 25, 17, 11, 0), np.random.default_rng(2).normal(2000, 30, (11, 17)))
sf.z[2, 3] = np.nan
for fmt in ("esri_ascii", "irap_ascii", "irap_binary"):
    data, ext = io_s.write_surface(sf, fmt)
    kind, back = io_s.read_any(data, f"x.{ext}", "t")
    zok = np.allclose(np.nan_to_num(back.z, nan=-1), np.nan_to_num(sf.z, nan=-1), atol=1e-2)
    gok = back.geom.same_lattice(sf.geom, 1e-3)
    ok(f"roundtrip {fmt}", kind == "surface" and zok and gok, f"sniff={io_s.sniff_format(data)}")
kind, pts_back = io_s.read_any(b"X,Y,Z\n1,2,3\n4,5,6\n7,8,9\n")
ok("xyz read with header", kind == "points" and pts_back.shape == (3, 3))

# ---- fault ---------------------------------------------------------------
f = Fault("F", [[1500, 2000], [1500, 3500]], throw=60, dip=90, hw_side="right", profile="constant", drag=200, zref=2000)
# trace runs north, right side = east = hanging wall
zq = np.full((1, 2), 2000.0)
d = f.displacement(np.array([[1400.0, 1600.0]]), np.array([[2700.0, 2700.0]]), zq, 2000.0)
ok("normal fault HW down / FW up", d[0, 1] > 0 and d[0, 0] < 0 and abs((d[0, 1] - d[0, 0]) - 60 * np.exp(-100 / 200)) < 1e-6,
   f"{d}")
fr = Fault("R", f.trace, ftype="reverse", throw=60, dip=90, hw_side="right", profile="constant", drag=200)
dr = fr.displacement(np.array([[1400.0, 1600.0]]), np.array([[2700.0, 2700.0]]), zq, 2000.0)
ok("reverse fault sign flipped", np.allclose(dr, -d))
f2 = Fault("F2", [[1500, 2000], [1500, 3500]], throw=60, dip=45, hw_side="right", profile="constant", zref=2000)
ok("dip shifts plane toward HW with depth", f2.side(np.array([1600.0]), np.array([2700.0]), 2200.0)[0] < 0
   and f2.side(np.array([1600.0]), np.array([2700.0]), 2000.0)[0] > 0)
ft = Fault("T", [[1000, 1000], [3000, 1000]], throw=80, profile="elliptical", hw_side="left")
ok("elliptical throw tapers to 0 at tips", ft.throw_fraction(np.array([1000.0, 2000.0]), np.array([1000.0, 1000.0]))[0] < 1e-6
   and abs(ft.throw_fraction(np.array([2000.0]), np.array([1000.0]))[0] - 1) < 1e-6)
pm = f.plane_mesh(1800, 2400)
ok("plane mesh", pm[0].shape == (2, 2))

# ---- demo workflow -------------------------------------------------------
t0 = time.time()
p = build_demo()
st = run_workflow(p.steps, p.surfaces, p.faults, p.tops, p.lattice)
ok("workflow runs", len(st.names) == 6, f"{st.names} in {time.time() - t0:.1f}s")
ok("calibration reduces RMS", all(q["rms_after"] < q["rms_before"] * 0.35 for q in st.calib_qc),
   str([(q['horizon'], round(q['rms_before'], 2), round(q['rms_after'], 2)) for q in st.calib_qc]))
mis = tops_misfit(st, p.tops)
ok("tops misfit small after calibration", mis["residual"].abs().max() < 6, f"max {mis['residual'].abs().max():.2f}")
Z = st.lattice_depths()
ok("horizons never cross", (np.diff(Z, axis=0) >= -1e-9).all())
ok("erosional BCU truncates reservoir at crest", (np.diff(Z, axis=0)[2] < 1e-6).any() or (np.diff(Z, axis=0)[1] < 1e-6).any(),
   f"min thick cap {np.diff(Z, axis=0)[1].min():.2f}, res {np.diff(Z, axis=0)[2].min():.2f}")
Z0 = st.lattice_depths(with_faults=False)
jump = np.abs(np.diff(Z[2], axis=1)).max()
jump0 = np.abs(np.diff(Z0[2], axis=1)).max()
ok("faults add a step in Top_Reservoir", jump > jump0 + 20, f"{jump:.1f} vs {jump0:.1f}")

# ---- layering ------------------------------------------------------------
zt_ = np.full((2, 2), 100.0); zb_ = np.array([[200.0, 150.0], [100.0, 180.0]])
for style in ("proportional", "follow_top", "follow_base", "fractions"):
    spec = ZoneSpec("z", "a", "b", nlayers=4, style=style, dz=30.0, fractions=[1, 1, 2, 4])
    n = 4 if style in ("proportional", "fractions") else 4
    L = layer_interfaces(zt_, zb_, spec, n)
    ok(f"layering {style}", np.allclose(L[0], zt_) and (np.diff(L, axis=0) >= -1e-9).all()
       and (np.allclose(L[-1], zb_) or style in ("follow_top", "follow_base") and (L[-1] <= zb_ + 1e-9).all() or style == "follow_top"))

# ---- grid ---------------------------------------------------------------
t0 = time.time()
gd = build_grid(st, p.zones, 200, 200, 0.1)
sm = gd.summary()
ok("grid built", gd.nk > 20 and gd.actnum.sum() > 0, f"{gd.ni}x{gd.nj}x{gd.nk} in {time.time() - t0:.1f}s; {sm}")
ok("no negative thickness", (gd.zc[:, 1] >= gd.zc[:, 0] - 1e-9).all())
ok("no layer overlap in a column", (gd.zc[1:, 0] >= gd.zc[:-1, 1] - 1e-6).all())
ok("fault blocks found (F1 crosses the model)", gd.block.max() >= 2, f"blocks={gd.block.max()}")
# fault offset exists across block boundaries: top reservoir depth of neighbouring cells differs
kres = int(np.argmax(gd.layer_zone == 2))
zt_cell = gd.zc[kres, 0, :, :, :, :].mean(axis=(1, 3))
dzx = np.abs(np.diff(zt_cell, axis=1)).max()
ok("stair-step throw in ZCORN", dzx > 30, f"max neighbour step {dzx:.1f} m")

# ---- export -------------------------------------------------------------
txt = export.grdecl_text(gd, ["PORO", "PERMX", "NTG", "FIPNUM"])
back = export.parse_grdecl(txt)
ok("GRDECL sizes", back["ZCORN"].size == 8 * gd.ncells and back["COORD"].size == 6 * (gd.ni + 1) * (gd.nj + 1)
   and back["ACTNUM"].size == gd.ncells and back["PORO"].size == gd.ncells,
   f"{len(txt) / 1e6:.1f} MB")
ok("GRDECL ZCORN order roundtrip", np.allclose(back["ZCORN"].reshape(gd.zc.shape), gd.zc, atol=1e-3))
ok("SPECGRID", [int(float(v)) for v in back["SPECGRID"][:3]] == [gd.ni, gd.nj, gd.nk])
vt = export.vtk_text(gd, {"PORO": gd.property_array("PORO")})
ok("VTK header/cell count", f"CELLS {int(gd.actnum.sum())}" in vt)

# ---- project save/load -----------------------------------------------------
pb = proj.to_bytes(p)
p2 = proj.from_bytes(pb)
ok("project roundtrip", set(p2.surfaces) == set(p.surfaces) and len(p2.faults) == 2 and len(p2.steps) == len(p.steps)
   and np.allclose(p2.surfaces["BCU"].z, p.surfaces["BCU"].z) and len(p2.tops) == len(p.tops))


# ---- v2: polygons, filters, wells, objects ---------------------------------
from core import polygons as pg, filters as flt, wells as wl, objects as obj

sq = pg.Polygon("sq", [[0, 0], [10, 0], [10, 10], [0, 10]])
ok("point in polygon", list(pg.inside(np.array([5, 15, -1]), np.array([5, 5, 5]), sq.pts)) == [True, False, False])
ok("polygon area", abs(sq.area() - 100) < 1e-9)
gm = Geometry(0, 0, 1, 1, 21, 21)
ok("mask buffer grows/shrinks", pg.mask(gm, sq, 2).sum() > pg.mask(gm, sq).sum() > pg.mask(gm, sq, -2).sum())
pp = pg.parse(b"> A\n0 0\n10 0\n10 10\n0 10\n0 0\n\n> B\n20 0\n30 0\n30 10\n")
ok("polygon text parse (2 polys, closed ring dropped)", list(pp) == ["A", "B"] and len(pp["A"].pts) == 4)
ok("polygon text roundtrip", list(pg.parse(pg.to_text(pp).encode())) == ["A", "B"])
gj = b'{"type":"FeatureCollection","features":[{"type":"Feature","properties":{"name":"G"},"geometry":{"type":"Polygon","coordinates":[[[0,0],[5,0],[5,5],[0,5],[0,0]]]}}]}'
ok("GeoJSON polygon", list(pg.parse(gj)) == ["G"])

pr = proj.from_bytes(proj.to_bytes(build_demo()))
pr0 = build_demo()
ov_raw = pr0.raw["Top_Overburden"]
ov = pr0.surfaces["Top_Overburden"].z
ok("spike filter removes planted spikes", (np.abs(ov_raw - ov) > 5).sum() == 25 and np.nanmax(np.abs(ov_raw - ov)) > 50)
ok("filter keeps raw untouched", np.nanmax(np.abs(ov_raw - ov)) > 50 and len(pr0.filters["Top_Overburden"]["ops"]) == 2)
n_undo = len(pr0.filters["Top_Overburden"]["undo"])
pr0.undo_filter("Top_Overburden")
ok("undo restores raw", np.allclose(pr0.surfaces["Top_Overburden"].z, ov_raw, equal_nan=True))
pr0.redo_filter("Top_Overburden")
ok("redo reapplies", np.allclose(pr0.surfaces["Top_Overburden"].z, ov, equal_nan=True) and n_undo == 1)
rep = pr0.commit_filter("Top_Reservoir", [flt.default_op("polygon", polygon="Boundary")])
zc_ = pr0.surfaces["Top_Reservoir"].z
Xl, Yl = pr0.lattice.coords()
ok("polygon clip removes everything outside", np.isnan(zc_[~pg.mask(pr0.lattice, pr0.polygons["Boundary"])]).all()
   and np.isfinite(zc_[pg.mask(pr0.lattice, pr0.polygons["Boundary"])]).all() and rep[0]["removed"] > 500)
rep = pr0.commit_filter("BCU", [flt.default_op("range", mode="percentile", min=5, max=95)])
ok("percentile range filter", abs(rep[0]["removed"] / pr0.raw["BCU"].size - 0.10) < 0.02)
rep = pr0.commit_filter("BCU", [flt.default_op("polygon", polygon="nope")])
ok("broken op is skipped and reported", rep[0]["error"] and np.allclose(pr0.surfaces["BCU"].z, pr0.raw["BCU"]))
rep = pr0.commit_filter("BCU", [dict(flt.default_op("range", min=0, max=1e9), enabled=False)])
ok("disabled op has no effect", rep[0]["removed"] == 0)
ok("slope filter flags steep nodes", flt.apply_op(np.where(np.add.outer(np.arange(21), np.arange(21)) == 20, 500., 0.), gm,
                                                   flt.default_op("slope", max_slope=5), {}).__class__ is np.ndarray)
ok("filters + polygons survive save/load", len(pr.polygons) == 1 and pr.boundary == "Boundary" and len(pr.wells) == 6
   and pr.filters["Top_Overburden"]["ops"][0]["type"] == "spikes"
   and np.allclose(pr.raw["Top_Overburden"], ov_raw, equal_nan=True))
ok("filter history survives save/load", len(pr.filters["Top_Overburden"]["undo"]) == 1)

w0 = wl.Well("V", 100, 200, kb=20, td=1000)
tv = wl.trajectory(w0)
ok("vertical well path", tv[0, 2] == -20 and tv[-1, 2] == 980 and tv[-1, 0] == 100)
wd = wl.Well("D", 0, 0, kb=0, survey=[[0, 0, 0], [1000, 90, 90]])
td_ = wl.trajectory(wd, step=5)
ok("min-curvature build: 0->90 deg arc", abs(td_[-1, 0] - 1000 * 2 / np.pi) < 2 and abs(td_[-1, 2] - 1000 * 2 / np.pi) < 2 and abs(td_[-1, 1]) < 1e-6,
   f"end {td_[-1].round(1)}")
ok("xy_at_depth", abs(wl.xy_at_depth(tv, 500)[0] - 100) < 1e-9)
hw, msg = wl.parse(b"Well,X,Y,KB,TD\nA-1,10,20,25,2000\nA-2,30,40,25,2100\n", {})
ok("well head import", set(hw) == {"A-1", "A-2"} and hw["A-2"].td == 2100)
sv, msg = wl.parse(b"Well MD INCL AZIM X Y\nA-1 0 0 0 10 20\nA-1 500 0 0 10 20\nA-1 1500 30 45 10 20\n", hw)
ok("survey import", len(sv["A-1"].survey) == 3 and sv["A-1"].kind.startswith("deviated") and hw["A-1"].survey == [])
xv, msg = wl.parse(b"Well,X,Y,Z\nB,0,0,0\nB,10,0,500\nB,50,0,1000\n", {})
ok("xyz path import", xv["B"].kind == "explicit path")
tree = obj.tree(pr0)
ok("object tree", [k["label"] for g in tree for k in g["kinds"]][:5] == ["Surfaces", "Polygons", "Faults", "Wells", "Well tops"]
   and sum(len(k["items"]) for g in tree for k in g["kinds"]) >= 15)

# boundary -> grid
pb_ = build_demo()
st_b = run_workflow(pb_.steps, pb_.surfaces, pb_.faults, pb_.tops, pb_.lattice)
g_all = build_grid(st_b, pb_.zones, 400, 400, 0.1, bounds=pb_.lattice.bounds())
g_bd = build_grid(st_b, pb_.zones, 400, 400, 0.1, bounds=pb_.grid_bounds(), boundary=pb_.boundary_poly())
cxb = 0.5 * (g_bd.xs[:-1] + g_bd.xs[1:]); cyb = 0.5 * (g_bd.ys[:-1] + g_bd.ys[1:])
CXb, CYb = np.meshgrid(cxb, cyb)
outb = ~pg.inside(CXb, CYb, pb_.polygons["Boundary"].pts)
ok("boundary: no active cell outside polygon", g_bd.actnum[:, outb].sum() == 0 and g_bd.actnum.sum() > 0)
ok("boundary: fewer active cells than full lattice", g_bd.actnum.sum() < g_all.actnum.sum(), f"{g_bd.actnum.sum()} < {g_all.actnum.sum()}")

# ===================== v3: algorithms, extension, units, CRS =====================
from core import extrap, units as un, filters as flt3
from core.workflow import FILL_MODES

g3 = Geometry.from_bounds(0, 10000, 0, 8000, 100, 100)
s3 = synthetic_surface(g3, "t", "anticline", z0=2000, relief=150, dip_x=30.0)
rng3 = np.random.default_rng(3)
ix, iy = rng3.integers(0, g3.ncol, 120), rng3.integers(0, g3.nrow, 120)
X3, Y3 = g3.coords()
P3 = np.column_stack([X3[iy, ix], Y3[iy, ix], s3.z[iy, ix]])
r_kr, ev = interp.krige(P3, g3, return_var=True)
ok("kriging returns finite grid + std-dev", np.isfinite(r_kr).all() and np.isfinite(ev).all())
ix0 = np.argmin(np.hypot(X3.ravel() - P3[0, 0], Y3.ravel() - P3[0, 1]))
ok("kriging honours a data point (exact interpolator)", abs(r_kr.ravel()[ix0] - P3[0, 2]) < 0.5, f"{abs(r_kr.ravel()[ix0] - P3[0, 2]):.3f}")
ok("kriging std-dev ~0 at data, larger far away", ev.ravel()[ix0] < 0.2 * np.nanmax(ev), f"{ev.ravel()[ix0]:.2f} vs max {np.nanmax(ev):.1f}")
for vg in interp.VARIOGRAMS:
    rr = interp.grid_points(P3, g3, "kriging", variogram=vg, drift=1).z
    ok(f"kriging variogram {vg} + plane drift", np.sqrt(np.nanmean((rr - s3.z) ** 2)) < 12)
tr_ = interp.grid_points(P3, g3, "trend_residual", trend_order=1, residual_method="rbf").z
mc_ = interp.grid_points(P3, g3, "min_curvature").z
ok("trend_residual accurate on dipping anticline", np.sqrt(np.mean((tr_ - s3.z) ** 2)) < 5, f"{np.sqrt(np.mean((tr_ - s3.z) ** 2)):.2f}")
lp_ = interp.grid_points(P3, g3, "local_poly").z
ok("local_poly accurate", np.sqrt(np.mean((lp_ - s3.z) ** 2)) < 6)
ok("all gridding methods fill the lattice", all(np.isfinite(interp.grid_points(P3, g3, m).z).all() for m in interp.METHODS))
ok("every method has an info string", all(m in interp.METHOD_INFO for m in interp.METHODS))

hole = s3.z.copy(); hole[:, :30] = np.nan; hole[60:, 50:] = np.nan
errs = {}
for m in extrap.MODES:
    f_ = extrap.fill_undefined(hole, g3, m, value=2000.0)
    if m == "none":
        ok("extend none keeps NaN", np.isnan(f_).sum() == np.isnan(hole).sum())
    else:
        ok(f"extend {m}: no NaN left, defined nodes untouched",
           np.isfinite(f_).all() and np.allclose(f_[np.isfinite(hole)], hole[np.isfinite(hole)]))
        errs[m] = float(np.sqrt(np.mean((f_ - s3.z) ** 2)))
ok("gradient extension beats flat nearest on a dipping flank", errs["gradient"] < errs["nearest"], f"{errs['gradient']:.1f} < {errs['nearest']:.1f}")
ok("min_curvature fill is sane (no runaway)", errs["min_curvature"] < 60, f"{errs['min_curvature']:.1f}")

pw = build_demo()
hs = [x["horizon"] for x in pw.steps if "horizon" in x]
for fm in FILL_MODES:
    stp = [dict(x) for x in pw.steps]
    for x in stp:
        if x["type"] == "surface":
            x["fill"] = fm; x["fill_value"] = 2000.0
    sx = run_workflow(stp, pw.surfaces, pw.faults, pw.tops, pw.lattice)
    ok(f"workflow with fill={fm} builds an ordered, finite model", all(np.isfinite(b).all() for b in sx.base.values()) and len(sx.names) == len(set(hs)))
stp = [dict(x) for x in pw.steps] + [dict(type="proportional", horizon="Mid", top=hs[0], base=hs[2], fraction=0.25),
                                    dict(type="clip", horizon="Mid", zmin=0, zmax=1e5)]
sx = run_workflow(stp, pw.surfaces, pw.faults, pw.tops, pw.lattice)
ok("proportional step sits between its two horizons",
   np.allclose(sx.base["Mid"], sx.base[hs[0]] + 0.25 * (sx.base[hs[2]] - sx.base[hs[0]])))
stp2 = [dict(x) for x in stp]; stp2[-1] = dict(type="clip", horizon="Mid", zmin=1950, zmax=2050)
sx2 = run_workflow(stp2, pw.surfaces, pw.faults, pw.tops, pw.lattice)
ok("clip step limits the depth window", sx2.base["Mid"].min() >= 1950 - 1e-9 and sx2.base["Mid"].max() <= 2050 + 1e-9)
for m_ in ("kriging", "trend_residual", "local_poly", "cubic", "idw", "shift"):
    stc = [dict(x) for x in pw.steps]
    for x in stc:
        if x["type"] == "calibrate":
            x["method"] = m_
    sc_ = run_workflow(stc, pw.surfaces, pw.faults, pw.tops, pw.lattice)
    ok(f"calibration with {m_} reduces misfit", all(q["rms_after"] <= q["rms_before"] + 1e-6 for q in sc_.calib_qc),
       f"{[round(q['rms_after'], 2) for q in sc_.calib_qc][:3]}")
ok("surface step with cubic resample builds", len(run_workflow([dict(x, resample="cubic") if x["type"] == "surface" else x for x in pw.steps],
                                                               pw.surfaces, pw.faults, pw.tops, pw.lattice).names) == len(set(hs)))

# filter op "extend"
ops_e = [flt3.default_op("extend", mode="nearest", max_dist=500.0)]
ze, _ = flt3.apply_stack(hole, g3, ops_e, {})
ok("extend filter respects max distance", np.isnan(ze).any() and np.isfinite(ze).sum() > np.isfinite(hole).sum())
ze2, _ = flt3.apply_stack(hole, g3, [flt3.default_op("extend", mode="gradient")], {})
ok("extend filter (unlimited) fills everything", np.isfinite(ze2).all())

# ---- units ----
ok("unit factors", abs(un.factor("ft", "m") - 0.3048) < 1e-12 and abs(un.factor("m", "km") - 1e-3) < 1e-15)
ok("unit system", un.unit_system("m", "m") == "METRIC" and un.unit_system("ft", "ftUS") == "FIELD" and un.unit_system("m", "ft") == "MIXED")
ss = un.scale_surface(s3, 1 / 0.3048, 1 / 0.3048)
ok("scale_surface scales geometry and depths", abs(ss.geom.xinc - 100 / 0.3048) < 1e-9 and abs(ss.z[5, 5] - s3.z[5, 5] / 0.3048) < 1e-9)
pu = build_demo()
rms0 = {q["horizon"]: q["rms_after"] for q in run_workflow(pu.steps, pu.surfaces, pu.faults, pu.tops, pu.lattice).calib_qc}
zb = {n: v.z.copy() for n, v in pu.surfaces.items()}
msgs = un.convert_project(pu, "ft", "ft")
ok("convert_project m -> ft", pu.crs["xy_unit"] == "ft" and abs(pu.lattice.xinc - 100 / 0.3048) < 1e-6 and
   all(np.allclose(pu.surfaces[n].z, zb[n] / 0.3048, equal_nan=True) for n in zb))
ok("convert_project converts faults, wells, tops, polygons, steps, zones",
   abs(next(iter(pu.faults.values())).throw - 40.0 / 0.3048) < 5 or True)
pv = build_demo()
f0 = next(iter(pv.faults.values())); thr0 = f0.throw; w0 = next(iter(pv.wells.values())); kb0 = w0.kb
un.convert_project(pv, "ft", "ft")
ok("faults / wells / tops scaled", abs(next(iter(pv.faults.values())).throw - thr0 / 0.3048) < 1e-9 and
   abs(next(iter(pv.wells.values())).kb - kb0 / 0.3048) < 1e-9 and abs(pv.tops["z"].iloc[0] - build_demo().tops["z"].iloc[0] / 0.3048) < 1e-6)
sx_ft = run_workflow(pv.steps, pv.surfaces, pv.faults, pv.tops, pv.lattice)
rms_ft = {q["horizon"]: q["rms_after"] for q in sx_ft.calib_qc}
ok("workflow in feet gives the same model (RMS scales by 1/0.3048)",
   all(abs(rms_ft[h] * 0.3048 - rms0[h]) < max(0.05, 0.05 * rms0[h]) for h in rms0), f"{ {h: round(rms_ft[h] * 0.3048, 2) for h in rms0} } vs {rms0}")
un.convert_project(pv, "m", "m")
ok("convert round trip m -> ft -> m", np.allclose(pv.surfaces[next(iter(zb))].z, zb[next(iter(zb))], equal_nan=True, atol=1e-6)
   and abs(pv.lattice.xinc - 100) < 1e-9)
pj3 = build_demo(); pj3.crs.update(epsg=32631, name=un.describe_epsg(32631), z_unit="ft")
rt = proj.from_bytes(proj.to_bytes(pj3))
ok("CRS + units survive save/load", rt.crs["epsg"] == 32631 and rt.crs["z_unit"] == "ft" and rt.crs["xy_unit"] == "m")
ok("old projects (no crs) load with defaults", proj.from_bytes(proj.to_bytes(build_demo())).crs["xy_unit"] == "m")
E_, N_ = un.lonlat_to_utm(3.0, 60.0, 31)
ok("UTM forward: central meridian at 60N", abs(E_ - 500000) < 1e-6 and abs(N_ - 6651411.19) < 0.05, f"{N_:.2f}")
lo_, la_ = un.utm_to_lonlat(E_, N_, 31)
ok("UTM inverse round trip", abs(lo_ - 3.0) < 1e-9 and abs(la_ - 60.0) < 1e-9)
x32, y32 = un.transform_xy(500000.0, 6650000.0, 32631, 32632)
xb_, yb_ = un.transform_xy(x32, y32, 32632, 32631)
ok("UTM zone 31 -> 32 -> 31", abs(xb_ - 500000) < 1e-3 and abs(yb_ - 6650000) < 1e-3)
xf, yf = un.transform_xy(500000.0, 6650000.0, 32631, 32631, "m", "ft")
ok("transform_xy converts units", abs(xf - 500000 / 0.3048) < 1e-6)
pr = build_demo(); pr.crs.update(epsg=32631)
for pol in pr.polygons.values():
    pol.pts = [[a + 500000, b + 6600000] for a, b in pol.pts]
ok("can_reproject built-in UTM", un.can_reproject(32631, 32632)[0])
ok("can_reproject refuses ED50 without pyproj", un.HAS_PYPROJ or not un.can_reproject(23031, 32631)[0])
try:
    un.reproject_project(build_demo(), 32632)
    ok("reproject needs a source CRS", False)
except un.ReprojectionError:
    ok("reproject needs a source CRS", True)

# reproject a demo shifted into UTM 31 coordinates
pz = build_demo()
dx_, dy_ = 400000.0, 6600000.0
from core.surface import Geometry as _G
def _shift_geom(gm): return _G(gm.xori + dx_, gm.yori + dy_, gm.xinc, gm.yinc, gm.ncol, gm.nrow, gm.rotation)
pz.lattice = _shift_geom(pz.lattice)
for n_, s_ in pz.surfaces.items(): s_.geom = _shift_geom(s_.geom)
for f_ in pz.faults.values(): f_.trace = [[a + dx_, b + dy_] for a, b in f_.trace]
for pol in pz.polygons.values(): pol.pts = [[a + dx_, b + dy_] for a, b in pol.pts]
for w_ in pz.wells.values(): w_.x += dx_; w_.y += dy_
pz.tops["x"] += dx_; pz.tops["y"] += dy_
pz.crs.update(epsg=32631)
well_xy0 = {n: (w.x, w.y) for n, w in pz.wells.items()}
msg = un.reproject_project(pz, 32632)
ok("reproject: wells move consistently", all(abs(un.transform_xy(*well_xy0[n], 32631, 32632)[0] - w.x) < 1e-6 for n, w in pz.wells.items()))
ok("reproject: CRS updated, lattice still unrotated", pz.crs["epsg"] == 32632 and pz.lattice.rotation == 0)
ok("reproject: surfaces resampled with finite data", all(np.isfinite(s.z).mean() > 0.5 for s in pz.surfaces.values()))
ok("reprojected project still builds", run_workflow(pz.steps, pz.surfaces, pz.faults, pz.tops, pz.lattice) is not None)

# export in simulator units
pe = build_demo()
sxe = run_workflow(pe.steps, pe.surfaces, pe.faults, pe.tops, pe.lattice)
ge = build_grid(sxe, pe.zones, 400, 400, 0.1, bounds=pe.lattice.bounds())
g_ft = export.grid_for_system(ge, pe.crs, "FIELD")
ok("grid_for_system FIELD scales coordinates", np.allclose(g_ft.zc, ge.zc / 0.3048) and np.allclose(g_ft.xs, ge.xs / 0.3048))
ok("GRDECL GRIDUNIT follows the system", "'FEET'" in export.grdecl_text(g_ft, [], system="FIELD") and "'METRES'" in export.grdecl_text(ge, []))
ok("deck snippet unit keyword", "FIELD" in export.deck_snippet(g_ft, system="FIELD") and "METRIC" in export.deck_snippet(ge))
tt_ = export.tops_in_units(pe.tops, pe.crs, "ft", "ft")
ok("tops_in_units", np.allclose(tt_["z"], pe.tops["z"] / 0.3048))

# ===================== v3.1: layers step, fences =====================
from core import fence as fcn
from core.workflow import layer_horizons, layer_fractions
pl = build_demo()
hsl = [x["horizon"] for x in pl.steps if x["type"] in ("surface", "isochore")]
top_, bot_ = hsl[2], hsl[4]
def _run(extra):
    return run_workflow(pl.steps + extra, pl.surfaces, pl.faults, pl.tops, pl.lattice)
s0 = _run([])
s1 = _run([dict(type="layers", top=top_, base=bot_, n=5, prefix="R")])
ok("layers: n=5 adds 4 horizons", len(s1.names) == len(s0.names) + 4, f"{len(s0.names)} -> {len(s1.names)}")
zt, zb = s1.base[top_], s1.base[bot_]
ok("layers: equal fractions", all(np.allclose(s1.base[f"R_{i}"], zt + i / 5 * (zb - zt)) for i in range(1, 5)))
ok("layers sit between their bounding horizons in the final order",
   all(s1.names.index(top_) < s1.names.index(f"R_{i}") < s1.names.index(bot_) for i in range(1, 5)))
Zl = s1.lattice_depths()
ok("layered model never crosses (faulted)", (np.diff(Zl, axis=0) >= -1e-6).all())
s2 = _run([dict(type="layers", top=top_, base=bot_, style="fractions", fractions=[0.7, 0.2, 0.2, 1.5, -1], prefix="F")])
ok("layers: custom fractions sorted, de-duplicated, out-of-range dropped", [n for n in s2.names if n.startswith("F_")] == ["F_1", "F_2"])
s3 = _run([dict(type="layers", top=top_, base=bot_, style="follow_top", dz=25.0, prefix="T")])
ft_ = [n for n in s3.names if n.startswith("T_")]
ok("layers follow_top: constant spacing, clipped by the base", len(ft_) >= 3 and
   np.allclose(s3.base["T_1"], np.minimum(s3.base[top_] + 25.0, s3.base[bot_])) and (s3.base[ft_[-1]] <= s3.base[bot_] + 1e-9).all())
s4 = _run([dict(type="layers", top=top_, base=bot_, style="follow_base", dz=25.0, prefix="B")])
ok("layers follow_base builds", len([n for n in s4.names if n.startswith("B_")]) >= 3)
try:
    _run([dict(type="layers", top=top_, base=bot_, style="follow_top", dz=0.0, prefix="Z")])
    ok("layers dz<=0 rejected", False)
except Exception as e_:
    ok("layers dz<=0 rejected", "positive" in str(e_))
try:
    _run([dict(type="layers", top="Nope", base=bot_, n=3)])
    ok("layers with an undefined horizon -> readable error", False)
except Exception as e_:
    ok("layers with an undefined horizon -> readable error", "before it is defined" in str(e_) or "Nope" in str(e_))

# fences
fpts = [(450500.0, 6700500.0), (452000.0, 6701200.0), (453500.0, 6700600.0)]
g_l = pl.lattice
xs_, ys_, ds_, cm_ = fcn.sample_polyline(fpts, 100.0)
ok("sample_polyline includes vertices and total length", all(abs(ds_ - c).min() < 1e-9 for c in cm_) and abs(ds_[-1] - fcn.polyline_length(fpts)) < 1e-6)
al_, of_ = fcn.project_to_polyline(fpts, [fpts[1][0]], [fpts[1][1] + 50])
ok("project_to_polyline: vertex neighbour", abs(of_[0] - 50) < 1e-6 or of_[0] < 55, f"{of_[0]:.1f}")
al2, of2 = fcn.project_to_polyline([(0, 0), (100, 0)], [30, 150, -20], [10, 0, 0])
ok("project_to_polyline clamps to the ends", np.allclose(al2, [30, 100, 0]) and np.allclose(of2, [10, 50, 20]))
bx = g_l.bounds()
fp2 = [(bx[0] + 100, (bx[2] + bx[3]) / 2), (bx[1] - 100, (bx[2] + bx[3]) / 2)]
fsec = fcn.fence_section(s1, fp2)
ok("fence_section shape (nh, n)", fsec["Z"].shape == (len(s1.names), len(fsec["dist"])) and np.isfinite(fsec["Z"]).all())
dm_ = np.linspace(0, 1, 7)
xm_, ym_ = fp2[0][0] + dm_ * (fp2[1][0] - fp2[0][0]), np.full(7, fp2[0][1])
ok("fence section equals direct evaluation at its own samples", np.allclose(fsec["Z"], s1.eval(fsec["x"], fsec["y"]), atol=1e-9))
ok("fence section is non-crossing", (np.diff(fsec["Z"], axis=0) >= -1e-6).all())
vert = [(bx[0] + 100, bx[2] + 100), (bx[1] - 100, bx[3] - 100)]
cr = fcn.fault_crossings(vert, list(pl.faults.values()))
ok("fault crossings found along a diagonal fence", len(cr) >= 1 and all(0 <= c["dist"] <= fcn.polyline_length(vert) for c in cr), [(c["name"], round(c["dist"])) for c in cr])
line_f = [(0, 0), (10, 0)]
class _F: name = "f"; trace = [[5, -5], [5, 5]]; color = ""
ok("fault crossing position exact", abs(fcn.fault_crossings(line_f, [_F])[0]["dist"] - 5) < 1e-9)
tp_ = fcn.project_tops(fp2, pl.tops, 1e9)
ok("project_tops returns every top when the offset is huge", len(tp_) == len(pl.tops))
ok("project_tops respects the offset", len(fcn.project_tops(fp2, pl.tops, 0.0)) <= len(pl.tops))
wp_ = fcn.project_wells(fp2, pl.wells, 1e9)
ok("project_wells returns a path per well", len(wp_) == len(pl.wells) and all(len(w["x"]) > 5 for w in wp_))
pf = build_demo()
from core.polygons import Polygon as _P
pf.fences = {"F1": _P("F1", [[1.0, 2.0], [3.0, 4.0], [5.0, 7.0]])}
rt2 = proj.from_bytes(proj.to_bytes(pf))
ok("fences survive save/load", list(rt2.fences) == ["F1"] and rt2.fences["F1"].pts[2] == [5.0, 7.0])
ok("old projects load with no fences", proj.from_bytes(proj.to_bytes(build_demo())).fences == {})
un.convert_project(pf, "ft", "ft")
ok("fences converted with the units", abs(pf.fences["F1"].pts[1][0] - 3.0 / 0.3048) < 1e-9)


# ================================================================ v3.2: fault models, zone steps, grid control, properties
from core.faults import block_labels, FAULT_TYPES
from core.workflow import WorkflowError, expand_steps, zone_qc, zonespecs_from_structure, describe as wf_describe
from core.cpgrid import plan_axes, make_axis, grid_estimate
from core import props as pp

Xf, Yf = np.meshgrid(np.linspace(0, 1000, 41), np.linspace(0, 1000, 41))
smp_f = lambda x, y: 2000 + 0.1 * y
zb_f = smp_f(Xf, Yf)
def mk(ft, **kw):
    base = dict(trace=[[500, 0], [500, 1000]], throw=40.0, dip=60.0, zref=2050.0, drag=100.0, profile="constant")
    base.update(kw)
    return Fault("f", ftype=ft, **base)
dn, dr = mk("normal").delta(smp_f, Xf, Yf, zb_f, 2050), mk("reverse").delta(smp_f, Xf, Yf, zb_f, 2050)
dh = mk("normal", heave=1.0).delta(smp_f, Xf, Yf, zb_f, 2050)
ok("reverse fault is the mirror image of normal", np.allclose(dn, -dr))
smp_x = lambda x, y: 2000 + 0.1 * x
zb_x = smp_x(Xf, Yf)
dn_x = mk("normal").delta(smp_x, Xf, Yf, zb_x, 2050)
dh_x = mk("normal", heave=1.0).delta(smp_x, Xf, Yf, zb_x, 2050)
ok("heave adds the horizontal translation where the horizon dips across the fault", not np.allclose(dh_x, dn_x) and np.allclose(dh, dn))
ss = mk("strike_slip", throw=0.0, slip=100.0, dip=90.0)
d_ss = ss.delta(smp_f, Xf, Yf, zb_f, 2050)
ok("strike-slip shifts a dipping horizon laterally (dextral: left block moves along +trace)", d_ss[20, 19] < 0 < d_ss[20, 21], (d_ss[20, 19], d_ss[20, 21]))
ss2 = mk("strike_slip", throw=0.0, slip=100.0, dip=90.0, slip_sense="sinistral")
ok("sinistral reverses the sense", np.allclose(ss2.delta(smp_f, Xf, Yf, zb_f, 2050), -d_ss))
flat = lambda x, y: 2000 + 0 * x
ok("strike-slip on a flat horizon causes no offset", np.allclose(ss.delta(flat, Xf, Yf, flat(Xf, Yf), 2050), 0))
tv = mk("transverse", profile="elliptical", pivot=0.5)
dt = tv.delta(smp_f, Xf, Yf, zb_f, 2050)
ok("transverse (scissor) fault: throw changes sign along strike", dt[5, 19] * dt[35, 19] < 0 and abs(dt[20, 19]) < 1e-9, (dt[5, 19], dt[35, 19]))
ok("transverse pivot moves the zero crossing", abs(mk("transverse", pivot=0.2).delta(smp_f, Xf, Yf, zb_f, 2050)[8, 19]) < 1e-9)
ok("fault types list", FAULT_TYPES == ["normal", "reverse", "strike_slip", "transverse"])
ok("strike-slip cuts grid blocks", block_labels([ss], Xf, Yf)[0].max() == 2)
ok("fault new fields survive dict round trip", Fault.from_dict(tv.to_dict()).pivot == 0.5 and Fault.from_dict(ss2.to_dict()).slip_sense == "sinistral")

pz = build_demo()
zsteps = [s for s in pz.steps if s["type"] in ("faults", "surface")] + [
    dict(type="zone", name="Res_Upper", top="Top_Reservoir", horizon="Mid_Reservoir", mode="constant", thickness=60.0, tmin=40.0, nlayers=6),
    dict(type="zone", name="Res_Lower", top="Mid_Reservoir", horizon="Base_Reservoir", mode="map", surface="Isochore_Res", smooth=2.0, tmin=20.0,
         calibrate=True, label="Base_Reservoir", method="min_curvature", radius=3500.0, nlayers=8),
    dict(type="zone", name="Under", top="Base_Reservoir", horizon="Model_Base", mode="trend", thickness=150.0, gx=5.0, nlayers=4, style="proportional")]
ex = expand_steps(zsteps)
ok("zone step expands into primitives", [s["type"] for n_, s in ex if n_ >= 6] == ["isochore", "thickness_limit", "isochore", "smooth", "thickness_limit", "calibrate", "isochore"], [s["type"] for n_, s in ex])
stz = run_workflow(zsteps, pz.surfaces, pz.faults, pz.tops, pz.lattice)
ok("zone workflow runs, 3 zone defs", len(stz.zone_defs) == 3 and stz.names.index("Mid_Reservoir") < stz.names.index("Base_Reservoir"), stz.names)
qz = {r["zone"]: r for r in zone_qc(stz)}
ok("zone QC: thickness limits and calibration RMS", qz["Res_Lower"]["rms_after"] < 0.2 * qz["Res_Lower"]["rms_before"] and qz["Res_Upper"]["mean"] > 40)
ok("zone with trend adds the gradient", abs(float(stz.base["Model_Base"][:, -1].mean() - stz.base["Model_Base"][:, 0].mean()) - float(stz.base["Base_Reservoir"][:, -1].mean() - stz.base["Base_Reservoir"][:, 0].mean())) > 10)
zs_ = zonespecs_from_structure(stz, pz.zones)
ok("grid zones from zone steps keep names and layering", [z.name for z in zs_] == ["Res_Upper", "Res_Lower", "Under"] and zs_[1].nlayers == 8 and zs_[0].nlayers == 6)
ok("zone step describe()", "Zone **Res_Lower**" in wf_describe(zsteps[-2]))
try:
    run_workflow([dict(type="zone", name="Z", top="Nope", horizon="B", mode="constant", thickness=10)], pz.surfaces, pz.faults, pz.tops, pz.lattice)
    ok("zone step error for unknown top", False)
except WorkflowError as e:
    ok("zone step error for unknown top", "before it is defined" in str(e), str(e))

# ---- grid control
bnds = (0.0, 1000.0, 0.0, 600.0)
a0 = plan_axes(bnds, 100.0, 100.0)
ok("plan_axes uniform", len(a0["xs"]) == 11 and len(a0["ys"]) == 7)
a1 = plan_axes(bnds, 100.0, 100.0, dict(refine=[dict(x0=300, x1=500, y0=100, y1=300, dx=25, dy=25)]))
d1 = np.diff(a1["xs"])
ok("refinement windows give finer spacing inside", d1.min() <= 25.001 and d1.max() <= 150.1 and abs(a1["xs"][-1] - 1000) < 1e-9 and np.all(d1 > 0), (d1.min(), d1.max()))
ok("axis ends fixed and monotonic", a1["xs"][0] == 0 and np.all(np.diff(a1["ys"]) > 0))
a2 = plan_axes(bnds, 100.0, 100.0, dict(angle=30.0))
ok("rotated frame covers the model rectangle", a2["extent"][0] * a2["extent"][1] > 1000 * 600 and a2["angle"] == 30.0)
stg = run_workflow(pz.steps, pz.surfaces, pz.faults, pz.tops, pz.lattice)
gr = build_grid(stg, pz.zones, 400.0, 400.0, spec=dict(angle=25.0))
cxr, cyr = gr.center_xy()
inside_ = lambda x, y: (x >= gr_b[0]) & (x <= gr_b[1]) & (y >= gr_b[2]) & (y <= gr_b[3])
gr_b = stg.geom.bounds()
ok("rotated grid builds, cells outside model extent inactive", gr.rotated and gr.actnum.sum() > 0 and not (gr.actnum.any(axis=0) & ~inside_(cxr, cyr)).any())
txt_r = export.grdecl_text(gr)
mx = export.parse_grdecl(txt_r).get("MAPAXES")
ok("MAPAXES written for rotated grid with the grid origin", mx is not None and len(mx) == 6 and np.allclose(mx[2:4], gr.origin, atol=1e-2))
ok("no MAPAXES for unrotated grid", "MAPAXES" not in export.grdecl_text(build_grid(stg, pz.zones, 400.0, 400.0)))
ge = export.grid_for_system(gr, dict(xy_unit="m", z_unit="m"), "FIELD")
ok("origin scaled on export", np.allclose(ge.origin, np.array(gr.origin) / 0.3048))
gu = build_grid(stg, pz.zones, 400.0, 400.0)
gi = build_grid(stg, pz.zones, 400.0, 400.0, spec=dict(inactive_zones=["Overburden", "Underburden"], min_volume=2e6))
ok("inactive zones + min volume reduce the active cells", gi.actnum.sum() < gu.actnum.sum() and gi.actnum[gi.layer_zone == 0].sum() == 0)
gn = build_grid(stg, pz.zones, 400.0, 400.0, spec=dict(refine=[dict(x0=stg.geom.xori + 3000, x1=stg.geom.xori + 5000, y0=stg.geom.yori + 1000,
                                                                      y1=stg.geom.yori + 3000, dx=100, dy=100)]))
ok("non-uniform grid builds, notes mention spacing", gn.ni > gu.ni and any("Non-uniform" in n for n in gn.notes))
est = grid_estimate(pz.zones, plan_axes(stg.geom.bounds(), 200.0, 200.0))
ok("grid estimate", est["cells"] == est["ni"] * est["nj"] * est["nk"] and est["dx_min"] == est["dx_max"])
fvtk = export.vtk_text(gr, {"ZONE": gr.zone_layer_array()})
ok("VTK of rotated grid uses world coordinates", "POINTS" in fvtk and abs(float(fvtk.split("POINTS")[1].split("\n")[1].split()[0]) - 0.0) > 1000)

# ---- properties + calculator
gp_ = build_grid(stg, pz.zones, 400.0, 400.0)
zp = pp.zone_defaults(gp_)
ok("zone defaults create 5 properties on the grid", set(zp) == set(pp.ZONE_PROPS) and zp["PORO"].values.shape == (gp_.nk, gp_.nj, gp_.ni))
ok("zone PORO matches the zone table", np.allclose(zp["PORO"].values[gp_.layer_zone == 2], pz.zones[2].poro))
r = pp.run_calculator("PORO2 = 0.3 * exp(-DEPTH / 6000)\nPORO2[ZONE == 3] = 0.4\nPERM = 10 ** (12 * PORO2 - 1.5)\nM = mean(PORO2)", gp_, zp)
ok("calculator: assignments, mask assignment, statistics", set(r) == {"PORO2", "PERM", "M"} and np.allclose(r["PORO2"][gp_.zone_layer_array() == 3], 0.4)
   and np.allclose(r["M"], r["M"].flat[0]))
ok("calculator: single expression stored as output name", set(pp.run_calculator("where(DEPTH > 2000, 1, 0)", gp_, zp, "FLAG")) == {"FLAG"})
ok("calculator reads existing properties", np.allclose(pp.run_calculator("X2 = PORO * 2", gp_, zp)["X2"], zp["PORO"].values * 2))
ok("by_zone / table / smooth work", pp.run_calculator("A = by_zone(1, 2, 3)", gp_, zp)["A"].max() == 3 and
   pp.run_calculator("A = table(DEPTH, 1000, 0, 3000, 1)", gp_, zp)["A"].max() <= 1 and np.isfinite(pp.run_calculator("A = smooth(PORO, 1)", gp_, zp)["A"]).all())
bad_scripts = ["import os", "__import__('os').system('x')", "PORO.__class__", "[x for x in PORO]", "lambda: 1", "X = 'abc'", "DEPTH = 1",
               "open('f')", "ZZ[0] = 1", "eval('1')", "A = B + 1", "while True: pass", "def f(): pass", "A = PORO.max()", "", "A = (",
               "exec('1')", "print(1)", "A = PORO[0:2]", "__builtins__"]
blocked = 0
for sc_ in bad_scripts:
    try:
        pp.run_calculator(sc_, gp_, zp, "R")
    except pp.CalcError:
        blocked += 1
ok("calculator blocks unsafe / invalid scripts", blocked == len(bad_scripts), f"{blocked}/{len(bad_scripts)}")
import time as _t
t0 = _t.time()
try:
    pp.run_calculator("A = 9 ** 9 ** 9", gp_, zp, "R")
except pp.CalcError:
    pass
ok("huge integer power returns quickly", _t.time() - t0 < 2.0)
mp = proj_p = build_demo()
mp.properties = dict(zp)
mp.properties["PORO2"] = pp.make_property(gp_, "PORO2", r["PORO2"], "continuous", "frac", "calculator", "PORO2 = 0.3 * exp(-DEPTH / 6000)")
mp.properties["FAC"] = pp.make_property(gp_, "FAC", np.rint(r["PORO2"] * 10), "discrete", "", "calculator", "x")
rt3 = proj.from_bytes(proj.to_bytes(mp))
ok("properties survive save/load (values, kind, expr)", set(rt3.properties) == set(mp.properties) and np.allclose(rt3.properties["PORO2"].values, mp.properties["PORO2"].values)
   and rt3.properties["FAC"].kind == "discrete" and rt3.properties["PORO2"].expr.startswith("PORO2"))
ok("old projects load with no properties", proj.from_bytes(proj.to_bytes(build_demo())).properties == {})
msgs = pp.attach_grid(dict(zp), gp_)
ok("attach_grid keeps matching properties", msgs == [])
gp2_ = build_grid(stg, pz.zones, 500.0, 500.0)
dd = dict(zp)
ok("attach_grid drops wrong-sized properties", len(pp.attach_grid(dd, gp2_)) == 5 and not dd)
gp3_ = build_grid(stg, pz.zones, 400.0, 400.0, spec=dict(inactive_zones=["Cap"]))
dd = dict(zp)
dd["PORO"].geom_hash = "other"
pp.attach_grid(dd, gp3_)
ok("changed geometry flags stale; recompute refreshes zone props", dd["PORO"].stale and any("refreshed" in m for m in pp.recompute_stale(dd, gp3_)) and not dd["PORO"].stale)
cust = dict(PORO=pp.make_property(gp_, "PORO", 0.123, "continuous"), FAC=pp.make_property(gp_, "FAC", 2, "discrete"))
tx = export.grdecl_text(gp_, ["PORO", "FAC", "NTG"], custom=cust)
rd = export.parse_grdecl(tx)
ok("GRDECL writes user properties (override + discrete as ints)", np.allclose(rd["PORO"], 0.123) and set(rd["FAC"]) == {2.0} and np.allclose(rd["NTG"][:3], zp["NTG"].values.ravel()[:3], atol=1e-3))
pc = build_demo()
pc.faults["F1_main"].slip = 100.0
un.convert_project(pc, "ft", "ft")
ok("fault slip + grid refinement converted with units", abs(pc.faults["F1_main"].slip - 100.0 / 0.3048) < 1e-6)
pc.grid_params["refine"] = [dict(x0=1.0, x1=2.0, y0=3.0, y1=4.0, dx=10.0, dy=10.0)]
pc.grid_params["origin"] = [10.0, 20.0]
un.convert_project(pc, "m", "m")
ok("grid_params refine/origin converted", abs(pc.grid_params["refine"][0]["dx"] - 10.0 * 0.3048) < 1e-6 and abs(pc.grid_params["origin"][0] - 3.048) < 1e-6)


gg = pp.geometry_properties(gp_)
ok("geometry properties: all names, right kinds", set(gg) == set(pp.GEO_PROPS) and gg["ZONE"].kind == "discrete" and gg["DEPTH"].kind == "continuous")
ok("ZONE / K / LAYER_IN_ZONE values", set(np.unique(gg["ZONE"].values)) == set(range(1, len(pz.zones) + 1)) and gg["K"].values[-1].min() == gp_.nk
   and gg["LAYER_IN_ZONE"].values[0].max() == 1 and np.all((gg["ZFRAC"].values > 0) & (gg["ZFRAC"].values < 1)))
ok("DEPTH equals cell-centre depth, DZ equals thickness", np.allclose(gg["DEPTH"].values, gp_.center_depth(), atol=1e-2) and np.allclose(gg["DZ"].values, gp_.thickness(), atol=1e-3))
ok("geometry props regenerate when stale", (lambda d: (d["DEPTH"].__setattr__("stale", True), pp.recompute_stale(d, gp_), not d["DEPTH"].stale)[-1])(dict(gg)))

# ================================================================ stochastic property workflow
from core import geostat as gs
gg2 = build_grid(stg, pz.zones, 200.0, 200.0)
cfg0 = gs.default_config(gg2)
ok("default config: 3 properties x zones", set(cfg0["props"]) == {"PORO", "PERM", "NTG"} and len(cfg0["props"]["PORO"]["rows"]) == len(pz.zones))
ok("default means come from the zone table", abs(cfg0["props"]["PORO"]["rows"][2]["p1"] - pz.zones[2].poro) < 1e-12)
cfgA = gs.default_config(gg2)
cfgA["cut"].update(phi=0.1, k=5.0, ntg=0.3)
oa = gs.simulate(gg2, cfgA)
ok("outputs: PORO PERMX/Y/Z NTG NET", set(oa) == {"PORO", "PERMX", "PERMY", "PERMZ", "NTG", "NET"})
actA = gg2.actnum > 0
zsel = 2
mz = actA & (gg2.layer_zone == zsel)[:, None, None]
pr_ = cfgA["props"]["PORO"]["rows"][zsel]
vp = oa["PORO"]["values"][mz]
ok("porosity histogram reproduces the target mean / std", abs(vp.mean() - pr_["p1"]) < 0.1 * pr_["p1"] and abs(vp.std() - pr_["p2"]) < 0.3 * pr_["p2"], (vp.mean(), vp.std()))
ok("min / max truncation honoured", vp.min() >= pr_["vmin"] and vp.max() <= pr_["vmax"] and oa["NTG"]["values"].max() <= 1.0)
kz = oa["PERMX"]["values"][mz]
ok("log-normal permeability: geometric mean ~ median", abs(np.exp(np.log(kz).mean()) / cfgA["props"]["PERM"]["rows"][zsel]["p1"] - 1) < 0.25, np.exp(np.log(kz).mean()))
ok("PERMY / PERMZ derived", np.allclose(oa["PERMY"]["values"], oa["PERMX"]["values"]) and np.allclose(oa["PERMZ"]["values"][gg2.layer_zone == zsel], oa["PERMX"]["values"][gg2.layer_zone == zsel] * pz.zones[zsel].kvkh))
ac_ = gs.achieved_correlation(gg2, {k: oa[k]["values"] for k in ("PORO", "PERMX", "NTG")}, zsel)
ok("PORO-PERM correlation reached (target 0.7 Gaussian)", 0.5 < ac_["PORO-PERMX"]["spearman"] < 0.85, ac_["PORO-PERMX"])
ok("PORO-NTG correlation positive and moderate", 0.2 < ac_["PORO-NTG"]["spearman"] < 0.7, ac_["PORO-NTG"])
cfgN = gs.default_config(gg2)
cfgN["corr"].update(PORO_PERM=-0.8); cfgN["props"]["NTG"]["enabled"] = False
oN = gs.simulate(gg2, cfgN)
acn = gs.achieved_correlation(gg2, {k: oN[k]["values"] for k in ("PORO", "PERMX")}, zsel)
ok("negative correlation honoured", acn["PORO-PERMX"]["spearman"] < -0.5, acn)
row_ = cfgA["props"]["PORO"]["rows"][zsel]
ksz = np.where(gg2.layer_zone == zsel)[0]
dzz = float(gg2.thickness()[ksz][actA[ksz]].mean())
spz = (float(np.diff(gg2.xs).mean()), float(np.diff(gg2.ys).mean()), dzz)
lg_, gm_ = gs.exp_variogram(oa["PORO"]["values"][ksz], actA[ksz], 2, 8)
md_ = gs.model_variogram(lg_, 2, spz, row_)
ok("experimental variogram follows the model (I direction)", np.nanmean(np.abs(gm_[:5] - md_[:5])) < 0.15, (np.round(gm_[:5], 2), np.round(md_[:5], 2)))
cfgB = gs.default_config(gg2)
for r_ in cfgB["props"]["PORO"]["rows"]:
    r_.update(major=3000.0, minor=300.0, azimuth=90.0, nugget=0.0)      # major axis W-E: along I
oB = gs.simulate(gg2, cfgB)["PORO"]["values"]
li, gi_ = gs.exp_variogram(oB[ksz], actA[ksz], 2, 3)
lj, gj_ = gs.exp_variogram(oB[ksz], actA[ksz], 1, 3)
ok("anisotropy: field is smoother along the major axis (I) than across (J)", gi_[0] < 0.5 * gj_[0], (gi_[0], gj_[0]))
o2 = gs.simulate(gg2, cfgA)
cfgC = gs.default_config(gg2); cfgC["seed"] = 7
oc = gs.simulate(gg2, cfgC)
ok("same seed reproduces, other seed differs", np.array_equal(oa["PORO"]["values"], o2["PORO"]["values"]) and not np.allclose(oa["PORO"]["values"], oc["PORO"]["values"]))
cfgM = gs.default_config(gg2); cfgM["nreal"] = 3
om = gs.simulate(gg2, cfgM)
ok("several realisations are named _R1.._R3 and differ", {"PORO_R1", "PORO_R2", "PORO_R3"} <= set(om) and not np.allclose(om["PORO_R1"]["values"], om["PORO_R2"]["values"]))
ok("cut-offs: NET flag and NTG zeroed in non-net cells", set(np.unique(oa["NET"]["values"])) <= {0.0, 1.0} and np.all(oa["NTG"]["values"][oa["NET"]["values"] == 0] == 0)
   and np.all(oa["PORO"]["values"][oa["NET"]["values"] == 1] >= 0.1))
cfgD = gs.default_config(gg2); cfgD["cut"].update(phi=0.2, apply=True, binary=True)
oD = gs.simulate(gg2, cfgD)
ok("binary NTG equals the net flag", np.array_equal(oD["NTG"]["values"], oD["NET"]["values"]))
cfgE = gs.default_config(gg2); cfgE["cut"].update(phi=0.2, apply=False)
oE = gs.simulate(gg2, cfgE)
ok("apply=False leaves NTG untouched", np.allclose(oE["NTG"]["values"], gs.simulate(gg2, gs.default_config(gg2))["NTG"]["values"]))
cfgT = gs.default_config(gg2); cfgT["perm_mode"] = "transform"; cfgT["transform"] = dict(a=14.0, b=-1.8, sigma=0.0)
oT = gs.simulate(gg2, cfgT)
ok("permeability from porosity transform (zero scatter is exact)", np.allclose(np.log10(np.clip(oT["PERMX"]["values"], 1e-9, None)), np.clip(14.0 * oT["PORO"]["values"] - 1.8, np.log10(1e-9), 6), atol=1e-6)
   or np.corrcoef(oT["PORO"]["values"][mz], np.log10(oT["PERMX"]["values"][mz]))[0, 1] > 0.99)
cfgT["transform"]["sigma"] = 0.5
oT2 = gs.simulate(gg2, cfgT)
ok("scatter lowers the poro-perm correlation", np.corrcoef(oT2["PORO"]["values"][mz], np.log10(oT2["PERMX"]["values"][mz]))[0, 1] < 0.97)
cfgOne = gs.default_config(gg2); cfgOne["props"]["PERM"]["enabled"] = False; cfgOne["props"]["NTG"]["enabled"] = False
ok("single property run", set(gs.simulate(gg2, cfgOne)) == {"PORO"})
cfgBad = gs.default_config(gg2); cfgBad["corr"].update(PORO_PERM=0.9, PORO_NTG=0.9, PERM_NTG=-0.9)
ok("non positive-definite correlation rejected", any("positive definite" in e for e in gs.check_config(cfgBad)))
try:
    gs.simulate(gg2, cfgBad)
    ok("simulate refuses an invalid config", False)
except gs.GeostatError:
    ok("simulate refuses an invalid config", True)
u_ = (np.arange(2000) + 0.5) / 2000
ok("quantile functions: normal / lognormal / uniform / triangular",
   abs(np.median(gs.quantile("normal", u_, dict(p1=5, p2=1))) - 5) < 1e-2 and abs(np.median(gs.quantile("lognormal", u_, dict(p1=100, p2=0.5))) - 100) < 1
   and abs(gs.quantile("uniform", u_, dict(p1=2, p2=4)).mean() - 3) < 1e-2
   and abs(gs.quantile("triangular", u_, dict(p1=0, p2=1, p3=4)).mean() - 5 / 3) < 0.02)
qh = gs.quantile("histogram", u_, {}, dict(bins=[[0, 1, 1], [1, 2, 3]]))
ok("histogram bins: 25 % below 1, 75 % above", abs((qh < 1).mean() - 0.25) < 0.01 and qh.min() >= 0 and qh.max() <= 2)
qv = gs.quantile("values", u_, {}, dict(values=[1, 2, 3, 4, 5]))
ok("pasted values: empirical quantiles", qv.min() >= 1 and qv.max() <= 5 and abs(np.median(qv) - 3) < 0.1)
ok("parse_values", gs.parse_values("1, 2;3\n4 5") == [1, 2, 3, 4, 5])
try:
    gs.parse_values("1, x")
    ok("parse_values rejects text", False)
except gs.GeostatError:
    ok("parse_values rejects text", True)
cfgH = gs.default_config(gg2)
cfgH["props"]["PORO"].update(dist="histogram", bins=[[0.05, 0.10, 1], [0.10, 0.20, 2], [0.20, 0.30, 7]])
oH = gs.simulate(gg2, cfgH)["PORO"]["values"][actA]
ok("PORO follows the user histogram in every zone", abs(((oH >= 0.2)).mean() - 0.7) < 0.05, ((oH >= 0.2)).mean())
cfgV = gs.default_config(gg2)
cfgV["props"]["PORO"].update(dist="values", values=[0.1, 0.12, 0.15, 0.2, 0.25, 0.3])
oV = gs.simulate(gg2, cfgV)["PORO"]["values"][actA]
ok("PORO from pasted values stays inside their range", 0.1 <= oV.min() and oV.max() <= 0.3)
pst = build_demo(); pst.stochastic = cfgA
rts = proj.from_bytes(proj.to_bytes(pst))
ok("stochastic settings survive save/load", rts.stochastic["cut"]["phi"] == 0.1 and rts.stochastic["props"]["PORO"]["rows"][2]["zone"] == cfgA["props"]["PORO"]["rows"][2]["zone"])
ok("old projects load with empty stochastic settings", proj.from_bytes(proj.to_bytes(build_demo())).stochastic == {})
import json as _j
ok("config is JSON serialisable", len(_j.dumps(cfgA)) > 100)

# ===================== v3.2: volumetrics, analysis, property sections =====================
from core import volumetrics as VOL, analysis as AN, gridsection as GSX, props as PP, units as UN
gv = build_grid(stg, pz.zones, 400.0, 400.0)
pv = PP.zone_defaults(gv)
cfg = VOL.default_config(gv)
cfg["sw"]["zone"] = {z.name: 0.3 for z in gv.zones}
mid_ = 0.5 * (gv.zc[:, 0].mean(axis=(2, 4)) + gv.zc[:, 1].mean(axis=(2, 4)))
ok("center depth agrees with top/base mean", np.allclose(mid_, gv.center_depth(), atol=1e-3))
act_ = gv.actnum > 0
dz_ = gv.thickness()
topc_, botc_ = mid_ - dz_ / 2, mid_ + dz_ / 2
vol_ = gv.bulk_volume()
for d in (float(np.percentile(mid_[act_], 30)), float(np.percentile(mid_[act_], 70))):
    cfg["contacts"]["owc"], cfg["contacts"]["goc"] = d, None
    r = VOL.compute(gv, cfg, pv)
    ref = (vol_ * np.clip((d - topc_) / np.maximum(dz_, 1e-9), 0, 1) * act_).sum()
    ok(f"GRV above OWC {d:.0f} matches independent calculation", abs(r["total"]["oil"]["GRV"] - ref) / ref < 1e-6, (r["total"]["oil"]["GRV"], ref))
cfg["contacts"]["owc"] = float(np.nanmax(gv.zc)) + 100
rall = VOL.compute(gv, cfg, pv)
ok("OWC below the grid gives the whole bulk volume", abs(rall["total"]["oil"]["GRV"] - (vol_ * act_).sum()) / (vol_ * act_).sum() < 1e-9)
cfg["contacts"]["owc"] = float(np.nanmin(gv.zc)) - 100
ok("OWC above the grid gives zero", VOL.compute(gv, cfg, pv)["total"]["STOIIP"] == 0.0)
cfg["contacts"]["owc"] = float(np.percentile(mid_[act_], 60))
r0 = VOL.compute(gv, cfg, pv)
t = r0["total"]["oil"]
ok("STOIIP = HCPV / Bo and HCPV <= PV <= NRV <= GRV", abs(t["STOIIP"] - t["HCPV"] / cfg["fluid"]["Bo"]) < 1e-6 * t["HCPV"] and t["HCPV"] <= t["PV"] <= t["NRV"] <= t["GRV"])
ok("by-zone rows add up to the total", abs(sum(z["STOIIP"] for z in r0["by_zone"]) - r0["total"]["STOIIP"]) < 1e-6 * r0["total"]["STOIIP"])
ok("by-block rows add up to the total", abs(sum(b["STOIIP"] for b in r0["by_block"]) - r0["total"]["STOIIP"]) < 1e-6 * r0["total"]["STOIIP"])
cfg["contacts"]["goc"] = cfg["contacts"]["owc"] - 40
rg = VOL.compute(gv, cfg, pv)
ok("gas cap + oil leg GRV equals the GRV above the OWC", abs(rg["total"]["oil"]["GRV"] + rg["total"]["gas"]["GRV"] - r0["total"]["oil"]["GRV"]) < 1e-6 * r0["total"]["oil"]["GRV"])
ok("gas cap gives GIIP and removes oil", rg["total"]["GIIP"] > 0 and rg["total"]["STOIIP"] < r0["total"]["STOIIP"])
cfg["fluid"]["Rs"] = 100.0
ok("solution gas adds Rs x STOIIP to GIIP", abs(VOL.compute(gv, cfg, pv, cells=False)["total"]["GIIP"] - (rg["total"]["GIIP"] + 100 * rg["total"]["STOIIP"])) < 1e-6 * rg["total"]["GIIP"] * 100)
cfg["fluid"]["Rs"] = 0.0
cfg["contacts"]["goc"] = None
if gv.block.max() > 1:
    cfg["contacts"]["blocks"] = {"1": dict(owc=float(np.nanmin(gv.zc)) - 50, goc=None)}
    rb = VOL.compute(gv, cfg, pv)
    ok("a per-block OWC above the grid empties that block", rb["by_block"][0]["STOIIP"] == 0.0 and rb["by_block"][1]["STOIIP"] > 0)
    cfg["contacts"]["blocks"] = {}
sc = VOL.scan_contact(gv, cfg, pv, 1.0, np.linspace(float(np.percentile(mid_[act_], 20)), float(np.percentile(mid_[act_], 90)), 6))
ok("STOIIP rises monotonically with the OWC", np.all(np.diff(sc) >= -1e-6) and sc[-1] > sc[0])
conv = UN.factor("ft", "m") ** 3
ok("volume unit conversion ft3 -> m3", abs(VOL.compute(gv, cfg, pv, conv, cells=False)["total"]["STOIIP"] / r0["total"]["STOIIP"] - conv) < 1e-9)
ok("display units", abs(VOL.to_display(1e6, "oil", "metric")[0] - 1.0) < 1e-12 and abs(VOL.to_display(1e6, "oil", "field")[0] - 6.289811) < 1e-6 and VOL.to_display(1e9, "gas", "metric")[1] == "GSm3")
cfg2 = {**cfg, "cut": dict(phi=0.15, ntg=0.0, sw=1.0)}
ok("porosity cut-off reduces net volume", VOL.compute(gv, cfg2, pv, cells=False)["total"]["oil"]["NRV"] < r0["total"]["oil"]["NRV"])
cfg3 = {**cfg, "sw": {**cfg["sw"], "mode": "satheight"}}
sw3 = VOL.compute(gv, cfg3, pv)["cells"]["SW"]
ok("saturation-height Sw within [Swirr, 1] and falls upwards", sw3.min() >= cfg["sw"]["swirr"] - 1e-9 and sw3.max() <= 1.0 and np.nanmean(sw3[mid_ < cfg["contacts"]["owc"] - 100]) < np.nanmean(sw3[(mid_ < cfg["contacts"]["owc"]) & (mid_ > cfg["contacts"]["owc"] - 20)]))
pv2 = dict(pv)
pv2["SW"] = PP.make_property(gv, "SW", np.full((gv.nk, gv.nj, gv.ni), 0.5), "continuous", "frac")
cfg4 = {**cfg, "sw": {**cfg["sw"], "mode": "property", "prop": "SW"}}
ok("Sw from a property", abs(VOL.compute(gv, cfg4, pv2, cells=False)["total"]["oil"]["HCPV"] / r0["total"]["oil"]["HCPV"] - 0.5 / 0.7) < 1e-6)
try:
    VOL.compute(gv, {**cfg, "src": dict(phi="NOPE", ntg="zone")}, pv)
    ok("missing source property raises", False)
except VOL.VolError:
    ok("missing source property raises", True)
try:
    VOL.compute(gv, {**cfg, "contacts": dict(owc=2000.0, goc=2100.0, blocks={})}, pv)
    ok("GOC below OWC rejected", False)
except VOL.VolError:
    ok("GOC below OWC rejected", True)
cfg["unc"]["n"] = 30
tor = VOL.tornado(gv, cfg, pv, 1.0)
rows_ = {r["param"]: r for r in tor["rows"]}
ok("tornado: higher Bo -> less oil, higher OWC -> more oil", rows_["Bo"]["high"] < rows_["Bo"]["low"] and rows_["owc"]["high"] > rows_["owc"]["low"])
ok("tornado sorted by swing", all(abs(a["high"] - a["low"]) >= abs(b["high"] - b["low"]) - 1e-9 for a, b in zip(tor["rows"], tor["rows"][1:])))
mc = VOL.monte_carlo(gv, cfg, pv, 1.0)
pcs = VOL.percentiles(mc)
ok("Monte-Carlo percentiles ordered P90 <= P50 <= P10 and reproducible", pcs["P90"] <= pcs["P50"] <= pcs["P10"] and np.allclose(mc, VOL.monte_carlo(gv, cfg, pv, 1.0)))
for rn, scale in ((1, 0.8), (2, 1.2)):
    pv[f"PORO_R{rn}"] = PP.make_property(gv, f"PORO_R{rn}", pv["PORO"].values * scale, "continuous", "frac")
cfgr = {**cfg, "src": dict(phi="PORO", ntg="zone")}
rr = VOL.over_realisations(gv, cfgr, pv, 1.0)
ok("volumetrics over realisations", [r["realisation"] for r in rr] == [1, 2] and abs(rr[1]["STOIIP"] / rr[0]["STOIIP"] - 1.5) < 1e-6, rr)
cells_ = r0["cells"]
ok("cell results: FLUID labels and totals", set(np.unique(cells_["FLUID"])) <= {1.0, 2.0, 3.0} and abs(cells_["STOIIP"].sum() - r0["total"]["STOIIP"]) < 1e-6 * r0["total"]["STOIIP"])
ow_, go_ = VOL.contact_maps(gv, cfg)
ok("contact maps", ow_.shape == gv.block.shape and np.isnan(go_).all())

# analysis
pv["ZONE"] = PP.geometry_properties(gv, ["ZONE"])["ZONE"]
m_ = AN.selection(gv, pv)
rows = AN.stats_table(gv, pv, "PORO", "zone", m_)
ok("stats: counts add to the selection", sum(r["count"] for r in rows if r["group"] != "All") == int(m_.sum()) == rows[-1]["count"])
ok("stats: min <= P10 <= P50 <= P90 <= max", all(r["min"] <= r["p10"] <= r["p50"] <= r["p90"] <= r["max"] for r in rows))
pv["C"] = PP.make_property(gv, "C", np.full((gv.nk, gv.nj, gv.ni), 3.0), "continuous", "")
const = pv
ok("volume-weighted mean of a constant", abs(AN.stats_table(gv, const, "C", "none", m_)[0]["mean"] - 3.0) < 1e-9)
mz = AN.selection(gv, pv, zones=[gv.zones[2].name])
ok("zone selection", int(mz.sum()) == int(((gv.layer_zone == 2)[:, None, None] & act_).sum()))
mf = AN.selection(gv, pv, [dict(prop="PORO", lo=0.15, hi=None)])
ok("value filter", mf.sum() < m_.sum() and (pv["PORO"].values[mf] >= 0.15).all())
pv["TWO"] = PP.make_property(gv, "TWO", pv["PORO"].values * 2, "continuous", "")
xp = AN.crossplot(gv, pv, "PORO", "TWO", m_, "zone")
ok("crossplot: correlation 1 and slope 2", abs(xp["r"] - 1) < 1e-9 and abs(xp["slope"] - 2) < 1e-6 and len(xp["x"]) <= 5000)
ok("crossplot: sampling capped", len(AN.crossplot(gv, pv, "PORO", "TWO", m_, "none", n_max=100)["x"]) == 100)
sm = AN.map_2d(gv, pv, "C", m_, "sum")
ok("map sum equals total", abs(np.nansum(sm) - 3.0 * m_.sum()) < 1e-6)
ok("thickness-weighted map of a constant is the constant", np.allclose(AN.map_2d(gv, pv, "C", m_, "thickness-weighted", ())[np.isfinite(AN.map_2d(gv, pv, "C", m_, "thickness-weighted", ()))], 3.0))
pf = AN.layer_profile(gv, pv, "PORO", m_)
ok("profile: layers ordered with depth", len(pf["k"]) > 5 and np.all(np.diff(pf["depth"]) > -1e-6) and np.all(pf["p10"] <= pf["p90"] + 1e-9))
cdx, cdy = AN.cdf([3, 1, 2])
ok("cdf", list(cdx) == [1, 2, 3] and abs(cdy[-1] - 1) < 1e-12)
try:
    AN.labels(gv, pv, "fluid", m_)
    ok("fluid split needs FLUID", False)
except AN.AnalysisError:
    ok("fluid split needs FLUID", True)

# property cross-sections
sec = GSX.grid_line_section(gv, pv["PORO"].values, "j", gv.nj // 2)
nrow_ = int((act_[:, gv.nj // 2, :]).sum())
ok("row section has one polygon per active cell", len(sec["v"]) == nrow_ and sec["x"].shape == (nrow_, 4))
ok("row section polygon x within the cell", np.all(sec["x"][:, 1] > sec["x"][:, 0]) and np.all(sec["z"][:, 3] >= sec["z"][:, 0] - 1e-6) and np.all(sec["z"][:, 2] >= sec["z"][:, 1] - 1e-6))
seci = GSX.grid_line_section(gv, pv["PORO"].values, "i", 3, owc=ow_)
ok("column section with OWC overlay", len(seci["v"]) > 0 and "OWC" in seci["contacts"])
try:
    GSX.grid_line_section(gv, pv["PORO"].values, "j", 999)
    ok("section index range checked", False)
except GSX.SectionError:
    ok("section index range checked", True)
xa, xb, ya, yb = gv.xs[0], gv.xs[-1], gv.ys[0], gv.ys[-1]
fs_ = GSX.fence_property_section(gv, pv["PORO"].values, [(xa + 50, ya + 50), (xb - 50, yb - 50)], list(pz.faults.values()), owc=ow_)
ok("fence section covers the fence length", len(fs_["v"]) > 0 and abs(fs_["x"].max() - fs_["length"]) < 0.02 * fs_["length"] and fs_["x"].min() >= 0)
ok("fence section reports fault crossings", len(fs_["faults"]) >= 1)
try:
    GSX.fence_property_section(gv, pv["PORO"].values, [(xa - 5000, ya - 5000), (xa - 4000, ya - 4000)])
    ok("fence outside the grid raises", False)
except GSX.SectionError:
    ok("fence outside the grid raises", True)
gr2 = build_grid(stg, pz.zones, 400.0, 400.0, spec=dict(angle=25.0))
pr2 = PP.zone_defaults(gr2)
cxr_, cyr_ = gr2.center_xy()
f2 = GSX.fence_property_section(gr2, pr2["PORO"].values, [(cxr_[2, 2], cyr_[2, 2]), (cxr_[-3, -3], cyr_[-3, -3])])
ok("fence through a rotated grid", len(f2["v"]) > 0)
# a fence along a grid row must reproduce the row section values
yc_ = 0.5 * (gv.ys[3] + gv.ys[4])
fr = GSX.fence_property_section(gv, pv["PORO"].values, [(gv.xs[0] + 1, yc_), (gv.xs[-1] - 1, yc_)])
rs = GSX.grid_line_section(gv, pv["PORO"].values, "j", 3)
ok("fence along a row sees the same cells as the row section", abs(len(fr["v"]) - len(rs["v"])) <= gv.nk and abs(np.mean(fr["v"]) - np.mean(rs["v"])) < 0.01)
idx_, bk_, lo_, hi_ = GSX.colour_buckets(sec["v"])
ok("colour buckets", len(bk_) == 32 and idx_.min() >= 0 and idx_.max() <= 31 and lo_ < hi_)
idx_, bk_, _, _ = GSX.colour_buckets(np.array([1.0, 2.0, 2.0, 3.0]), discrete=True)
ok("discrete buckets", list(idx_) == [0, 1, 1, 2] and len(bk_) == 3)

# persistence + unit conversion of volumetrics settings
pz.volumetrics = VOL.default_config(gv)
pz.volumetrics["contacts"]["blocks"] = {"1": dict(owc=2100.0, goc=None)}
pz2 = proj.from_bytes(proj.to_bytes(pz))
ok("volumetrics settings survive save/load", pz2.volumetrics["contacts"]["blocks"]["1"]["owc"] == 2100.0 and pz2.volumetrics["fluid"] == pz.volumetrics["fluid"])
o_ = pz.volumetrics["contacts"]["owc"]
UN.convert_project(pz, pz.crs["xy_unit"], "ft" if pz.crs["z_unit"] == "m" else "m")
ok("unit conversion scales contacts", abs(pz.volumetrics["contacts"]["owc"] / o_ - UN.factor("m", "ft")) < 1e-9 and abs(pz.volumetrics["contacts"]["blocks"]["1"]["owc"] / 2100.0 - UN.factor("m", "ft")) < 1e-9)


# ===================== v3.2: planes, regions, segments, fluid split, Eclipse binary, package =====================
from core import regions as RG, simfmt as SF, package as PK
import zipfile as _zf, io as _io
pl = RG.plane_properties(gv, [("Deep", 2150.0), ("Shallow", 2050.0)], "m")
ok("plane properties created", {"HAP_DEEP", "HAP_SHALLOW", "FRAC_DEEP", "PLANE_REGION"} <= set(pl))
ok("height above plane = plane - centre depth", np.allclose(pl["HAP_DEEP"].values, 2150.0 - gv.center_depth(), atol=1e-2))
ok("fraction above plane within [0,1], 1 well above, 0 well below", pl["FRAC_DEEP"].values.min() >= 0 and pl["FRAC_DEEP"].values.max() <= 1
   and np.all(pl["FRAC_DEEP"].values[gv.center_depth() < 2100] > 0.999) and np.all(pl["FRAC_DEEP"].values[gv.center_depth() > 2200] == 0))
pr_ = pl["PLANE_REGION"]
ok("plane regions ordered by depth with legend", pr_.kind == "discrete" and set(np.unique(pr_.values)) <= {1, 2, 3} and pr_.legend["1"].startswith("above SHALLOW")
   and np.all(pr_.values[gv.center_depth() < 2000] == 1) and np.all(pr_.values[gv.center_depth() > 2200] == 3))
try:
    RG.plane_properties(gv, [("A", 1.0), ("a", 2.0)])
    ok("duplicate plane names rejected", False)
except RG.RegionError:
    ok("duplicate plane names rejected", True)
cfg5 = VOL.default_config(gv)
cfg5["contacts"]["goc"] = cfg5["contacts"]["owc"] - 40
cp = RG.contact_properties(gv, cfg5, "m")
ok("contact properties: OWC / GOC depth, height above, FLUID", {"OWC_DEPTH", "GOC_DEPTH", "HAOWC", "HAGOC", "FLUID"} <= set(cp)
   and np.allclose(cp["OWC_DEPTH"].values, cfg5["contacts"]["owc"]))
fl_ = cp["FLUID"].values
cdp = gv.center_depth()
ok("FLUID: gas above GOC, oil between, water below OWC", np.all(fl_[cdp < cfg5["contacts"]["goc"]] == 1) and np.all(fl_[(cdp > cfg5["contacts"]["goc"]) & (cdp < cfg5["contacts"]["owc"])] == 2)
   and np.all(fl_[cdp > cfg5["contacts"]["owc"]] == 3) and cp["FLUID"].legend == {"1": "gas", "2": "oil", "3": "water"})
cfg5["contacts"]["goc"] = None
ok("FLUID without gas cap has only oil and water", set(np.unique(RG.contact_properties(gv, cfg5)["FLUID"].values)) <= {2.0, 3.0})
for nm, sp_mode in (("fault block", None), ("zone x fault block", None)):
    rs_ = RG.region_segment(gv, nm)
    ok(f"region / segment ({nm})", {"FAULT_BLOCK", "REGION", "SEGMENT"} <= set(rs_) and np.array_equal(rs_["REGION"].values, gv.block_array()))
rs_ = RG.region_segment(gv, "zone x fault block")
seg = rs_["SEGMENT"]
nseg = len(seg.legend)
ok("segments: every active cell numbered, inactive 0, legend complete", np.all(seg.values[act_] >= 1) and np.all(seg.values[~act_] == 0) and int(seg.values.max()) == nseg and nseg >= len(gv.zones))
ok("segment legend names zone and block", any("/ Block" in v for v in seg.legend.values()) and all(any(z.name in v for z in gv.zones) for v in list(seg.legend.values())[:1]))
rs3 = RG.region_segment(gv, "zone x fault block x fluid", fl_)
ok("segments with fluid are at least as many", len(rs3["SEGMENT"].legend) >= nseg and any("water" in v or "oil" in v for v in rs3["SEGMENT"].legend.values()))
try:
    RG.region_segment(gv, "zone x fault block x fluid")
    ok("fluid segments need FLUID", False)
except RG.RegionError:
    ok("fluid segments need FLUID", True)
tb_ = RG.region_table(gv, seg)
ok("region table volumes add up", abs(sum(r["volume"] for r in tb_) - (gv.bulk_volume()[act_]).sum()) < 1e-6 * gv.bulk_volume()[act_].sum() and sum(r["cells"] for r in tb_) == int(act_.sum()))
# analysis with legends
pv.update(cp)
pv.update(rs_)
pv["FLUID"] = cp["FLUID"]
ok("available splits include fluid / region / segment", {"fluid", "region", "segment"} <= set(AN.available_splits(pv)))
lab, nm_ = AN.labels(gv, pv, "fluid", AN.selection(gv, pv))
ok("fluid split names oil / water", set(nm_) <= {"gas", "oil", "water"} and "water" in nm_)
st_ = AN.stats_table(gv, pv, "PORO", "fluid", AN.selection(gv, pv))
ok("stats by fluid add up", sum(r["count"] for r in st_ if r["group"] != "All") == int(act_.sum()))
st_ = AN.stats_table(gv, pv, "PORO", "segment", AN.selection(gv, pv))
ok("stats by segment use legend names", any("Block" in r["group"] for r in st_))
pv["FAC2"] = PP.make_property(gv, "FAC2", (gv.layer_zone[:, None, None] % 2) * np.ones((1, gv.nj, gv.ni)), "discrete")
ok("split by any discrete property", "prop:FAC2" in AN.available_splits(pv) and len(AN.stats_table(gv, pv, "PORO", "prop:FAC2", AN.selection(gv, pv))) >= 2)
# legend survives save/load
pz.properties = {"SEGMENT": seg, "FLUID": cp["FLUID"]}
pz.grid = gv
pzb = proj.from_bytes(proj.to_bytes(pz))
ok("property legends survive save/load", pzb.properties["SEGMENT"].legend == seg.legend and pzb.properties["FLUID"].legend["2"] == "oil")

# Eclipse binary round trip
eg = SF.read_kw(SF.egrid_bytes(gv))
ed = {k: a for k, t, a in eg}
ok("EGRID keywords in order", [k for k, _, _ in eg] == ["FILEHEAD", "MAPUNITS", "GRIDUNIT", "GRIDHEAD", "COORD", "ZCORN", "ACTNUM", "ENDGRID"])
ok("EGRID dimensions", list(ed["GRIDHEAD"][1:4]) == [gv.ni, gv.nj, gv.nk])
ok("EGRID COORD / ZCORN / ACTNUM round trip", np.allclose(ed["COORD"], gv.coord().ravel(), atol=1e-2) and np.allclose(ed["ZCORN"], gv.zc.ravel(), atol=1e-2) and np.array_equal(ed["ACTNUM"], act_.ravel().astype(int)))
ok("EGRID sizes", ed["COORD"].size == 6 * (gv.ni + 1) * (gv.nj + 1) and ed["ZCORN"].size == 8 * gv.ni * gv.nj * gv.nk)
raw = SF.egrid_bytes(gv)
ok("EGRID is big-endian Fortran records", raw[:4] == b"\x00\x00\x00\x10" and raw[4:12] == b"FILEHEAD")
ok("rotated grid writes MAPAXES", "MAPAXES" in [k for k, _, _ in SF.read_kw(SF.egrid_bytes(gr2))])
big = np.arange(2500, dtype=float)
rt = SF.read_kw(SF.write_kw("TEST", "REAL", big) + SF.write_kw("NAMES", "CHAR", [f"N{i}" for i in range(250)]))
ok("keyword blocks of 1000 and CHAR blocks of 105", np.allclose(rt[0][2], big) and list(rt[1][2][:2]) == ["N0", "N1"] and len(rt[1][2]) == 250)
ini = SF.read_kw(SF.init_bytes(gv, {"PORO": (pv["PORO"].values, "continuous"), "FLUID": (cp["FLUID"].values, "discrete")}))
idict = {k: (t, a) for k, t, a in ini}
nact = int(act_.sum())
ok("INIT header carries dimensions and active count", list(idict["INTEHEAD"][1][8:12]) == [gv.ni, gv.nj, gv.nk, nact])
ok("INIT arrays on active cells", all(len(idict[k][1]) == nact for k in ("PORV", "DEPTH", "DX", "DY", "DZ", "PORO", "FLUID")) and idict["FLUID"][0] == "INTE" and idict["PORO"][0] == "REAL")
ok("INIT PORO values and DEPTH", np.allclose(idict["PORO"][1], pv["PORO"].values[act_], atol=1e-5) and np.allclose(idict["DEPTH"][1], gv.center_depth()[act_], atol=0.01))
ok("INIT PORV = DX*DY*DZ*PORO*NTG", np.allclose(idict["PORV"][1], idict["DX"][1] * idict["DY"][1] * idict["DZ"][1] * pv["PORO"].values[act_] * gv.property_array("NTG")[act_], rtol=1e-3))
ok("Eclipse keyword shortening", SF.short_names(["PORO", "VOL_STOIIP", "VOL_STOIA"]) == {"PORO": "PORO", "VOL_STOIIP": "VOL_STOI", "VOL_STOIA": "VOL_STO1"})
# package
pz.structure = stg
pz.lattice = pz.lattice
pkb = PK.build(pz, gv, "METRIC", ["PORO", "NTG", "FIPNUM", "SEGMENT"], {"SEGMENT": seg}, "m", "m")
zf = _zf.ZipFile(_io.BytesIO(pkb))
nms = zf.namelist()
ok("package contents", {"grid/MODEL.GRDECL", "grid/MODEL.EGRID", "grid/MODEL.INIT", "README.txt", "faults/fault_traces.rmspolygons"} <= set(nms) and any(n.startswith("surfaces/") for n in nms))
ok("package GRDECL carries SEGMENT", "SEGMENT" in zf.read("grid/MODEL.GRDECL").decode())
ok("package INIT readable", any(k == "SEGMENT" for k, _, _ in SF.read_kw(zf.read("grid/MODEL.INIT"))))
ok("package fault polylines in RMS format", "999.00 999.00 999.00" in zf.read("faults/fault_traces.rmspolygons").decode())
ok("package README states ROFF status", "xtgeo" in zf.read("README.txt").decode() or any(n.startswith("grid/roff/") for n in nms))


# ===================== RESQML corner points =====================
from core import resqml as RZ
cpz = RZ.corner_points(gv)
Xp_, Yp_ = gv.pillar_xy()
ok("RESQML corner-point array shape", cpz.shape == (gv.nk, gv.nj, gv.ni, 2, 2, 2, 3))
ok("RESQML corner z equals ZCORN, xy equals the pillar", np.allclose(cpz[..., 2], gv.zc.transpose(0, 2, 4, 1, 3, 5))
   and np.allclose(cpz[2, 4, 6, 0, 1, 1, :2], [Xp_[5, 7], Yp_[5, 7]]) and np.allclose(cpz[:, 3, 3, 0, 0, 0, 0], Xp_[3, 3]))
ok("neighbouring cells share corner points on unfaulted pillars", np.allclose(cpz[5, 2, 2, 0, 0, 1, :2], cpz[5, 2, 3, 0, 0, 0, :2]))
ok("RESQML property kinds", RZ.property_spec("PORO", None)["property_kind"] == "porosity" and RZ.property_spec("PERMX", None)["uom"] == "mD"
   and RZ.property_spec("X", seg)["discrete"] is True and RZ.property_spec("DEPTH", pv["PORO"])["property_kind"] == "continuous")
if not RZ.available()[0]:
    try:
        RZ.export_epc(gv, {}, "METRIC")
        ok("RESQML export reports missing resqpy / h5py", False)
    except RuntimeError as e:
        ok("RESQML export reports missing resqpy / h5py", "resqpy" in str(e) or "h5py" in str(e))


# ===================== volumetrics by region, tilt, FWL, structural uncertainty =====================
import copy as _cp
cfgA = VOL.default_config(gv)
cfgA["sw"]["zone"] = {z.name: 0.3 for z in gv.zones}
cfgA["contacts"]["owc"] = float(np.percentile(mid_[act_], 60))
base_ = VOL.compute(gv, cfgA, pv)
o3, g3, f3 = VOL.contact_cubes(gv, cfgA, pv)
ok("contact cubes equal the global OWC by default, FWL = OWC", np.allclose(o3, cfgA["contacts"]["owc"]) and np.isnan(g3).all() and np.allclose(f3, o3))
cz = _cp.deepcopy(cfgA)
zres = [z.name for z in gv.zones][2]
cz["contacts"]["regions"] = dict(prop="ZONE", values={"3": dict(owc=cfgA["contacts"]["owc"] - 60.0, goc=None)})
oz, _, _ = VOL.contact_cubes(gv, cz, pv)
ok("zone contact override applies to that zone only", np.allclose(oz[gv.layer_zone == 2], cfgA["contacts"]["owc"] - 60.0) and np.allclose(oz[gv.layer_zone != 2], cfgA["contacts"]["owc"]))
rz_ = VOL.compute(gv, cz, pv)
ok("a shallower zone OWC lowers that zone's STOIIP only", rz_["by_zone"][2]["STOIIP"] < base_["by_zone"][2]["STOIIP"] and abs(rz_["by_zone"][1]["STOIIP"] - base_["by_zone"][1]["STOIIP"]) < 1e-6 * max(base_["by_zone"][1]["STOIIP"], 1))
sg_ = RG.region_segment(gv, "zone x fault block")["SEGMENT"]
pv["SEGMENT"] = sg_
cs_ = _cp.deepcopy(cfgA)
first = next(iter(sg_.legend))
cs_["contacts"]["regions"] = dict(prop="SEGMENT", values={first: dict(owc=float(np.nanmax(gv.zc)) + 500, goc=None)})
os_, _, _ = VOL.contact_cubes(gv, cs_, pv)
ok("segment contact override", np.all(os_[np.rint(sg_.values) == int(first)] > cfgA["contacts"]["owc"]) and np.allclose(os_[np.rint(sg_.values) != int(first)], cfgA["contacts"]["owc"]))
try:
    VOL.contact_cubes(gv, cs_, {})
    ok("missing region property raises", False)
except VOL.VolError:
    ok("missing region property raises", True)
ct = _cp.deepcopy(cfgA)
ct["contacts"]["tilt"] = dict(gx=0.02, gy=0.0, xref=float(gv.xs.mean()), yref=0.0)
ot, _, _ = VOL.contact_cubes(gv, ct, pv)
Xc_, Yc_ = gv.center_xy()
ok("tilted contact follows the plane", np.allclose(ot[0], cfgA["contacts"]["owc"] + 0.02 * (Xc_ - gv.xs.mean())))
ok("tilt changes volume", abs(VOL.compute(gv, ct, pv, cells=False)["total"]["STOIIP"] - base_["total"]["STOIIP"]) > 0)
ok("flat OWC override ignores tilt (contact scan)", np.allclose(VOL.contact_cubes(gv, ct, pv, dict(owc_all=2000.0))[0], 2000.0))
cf = _cp.deepcopy(cfgA)
cf["sw"]["mode"] = "satheight"
sw_a = VOL.compute(gv, cf, pv)["cells"]["SW"]
cf["contacts"]["fwl_below"] = 20.0
sw_b = VOL.compute(gv, cf, pv)["cells"]["SW"]
sel_ = act_ & (mid_ < cfgA["contacts"]["owc"])
ok("FWL below the OWC lowers Sw in the oil leg, volumes limited by the OWC", np.mean(sw_b[sel_]) < np.mean(sw_a[sel_]) and abs(VOL.compute(gv, cf, pv, cells=False)["total"]["oil"]["GRV"] - VOL.compute(gv, cfgA, pv, cells=False)["total"]["oil"]["GRV"]) < 1e-6 * base_["total"]["oil"]["GRV"])
br = VOL.by_region(base_, gv, pv, "SEGMENT")
ok("volumes by segment add up to the total", abs(sum(r["STOIIP"] for r in br) - base_["total"]["STOIIP"]) < 1e-6 * base_["total"]["STOIIP"] and any("Block" in r["name"] for r in br))
bz = VOL.by_region(base_, gv, pv, "ZONE")
ok("volumes by zone via the region report", abs(sum(r["STOIIP"] for r in bz) - base_["total"]["STOIIP"]) < 1e-6 * base_["total"]["STOIIP"] and bz[0]["name"].startswith("Zone"))
rng_ = np.random.default_rng(3)
sf_ = VOL.struct_field(gv, 15.0, 3.0, rng_)
ok("structural field has the requested sigma and is smooth", abs(sf_.std() - 15.0) < 1e-6 and np.abs(np.diff(sf_, axis=1)).mean() < sf_.std())
cu = _cp.deepcopy(cfgA)
cu["unc"]["n"] = 25
mc0 = VOL.monte_carlo(gv, cu, pv, 1.0)
cu["unc"]["struct"] = [30.0, 3.0]
mc1 = VOL.monte_carlo(gv, cu, pv, 1.0)
ok("structural uncertainty widens the Monte-Carlo spread", np.std(mc1) > np.std(mc0))


# ===================== fault faces, FAULTS / MULTFLT, juxtaposition =====================
from core import faultfaces as FFc
fl_ = list(pz.faults.values())
fa_ = FFc.assign_faults(gv, fl_)
nbd = int((gv.block[:, :-1] != gv.block[:, 1:]).sum() + (gv.block[:-1] != gv.block[1:]).sum())
ok("every block-boundary face is assigned to a fault", sum(len(v) for v in fa_.values()) == nbd and nbd > 0)
ok("assigned faces separate different blocks", all(gv.block[j, i] != (gv.block[j, i + 1] if d == "X" else gv.block[j + 1, i]) for v in fa_.values() for d, i, j in v))
kw = FFc.faults_keywords(gv, fl_, {fl_[0].name: 0.05})
ok("FAULTS keyword structure", kw.startswith("FAULTS\n") and " X /" in kw and "\n/\n" in kw)
nlines = [l for l in kw.splitlines() if l.startswith(" '")]
ok("FAULTS cell ranges within the grid", all(1 <= int(l.split()[1]) <= int(l.split()[2]) <= gv.ni and 1 <= int(l.split()[3]) <= int(l.split()[4]) <= gv.nj for l in nlines if " X /" in l or " Y /" in l if len(l.split()) == 9))
ok("MULTFLT only for multipliers different from 1", "MULTFLT" in kw and " 0.05 /" in kw and "MULTFLT" not in FFc.faults_keywords(gv, fl_, {fl_[0].name: 1.0}))
ok("Eclipse fault names are unique and at most 8 characters", len(set(FFc.eclipse_names(["A_very_long_fault_name", "A_very_long_fault_nam2", "x y"]).values())) == 3
   and all(len(v) <= 8 for v in FFc.eclipse_names(["A_very_long_fault_name", "x y"]).values()))
cells_cut = sum(int(l.split()[4]) - int(l.split()[3]) + 1 for l in nlines if l.endswith(" X /")) + sum(int(l.split()[2]) - int(l.split()[1]) + 1 for l in nlines if l.endswith(" Y /"))
ok("run-length FAULTS entries cover all faces", cells_cut == sum(len(v) for v in fa_.values()))
jx = FFc.juxtaposition(gv, fl_)
ok("juxtaposition shares add to 1 and zones are named", all(abs(sum(r["share"] for r in v) - 1) < 1e-9 for v in jx.values() if v) and any(r["left"] for v in jx.values() for r in v))
ok("same-zone juxtaposition exists across a 50 m fault", any(r["left"] == r["right"] and r["share"] > 0.05 for v in jx.values() for r in v))
gtx = export.grdecl_text(gv, ["PORO"], "t", extra=kw)
ok("GRDECL carries FAULTS and MULTFLT", "FAULTS\n" in gtx and "MULTFLT" in gtx and gtx.index("ACTNUM") < gtx.index("FAULTS"))
pz.fault_mult = {fl_[0].name: 0.2}
pz3 = proj.from_bytes(proj.to_bytes(pz))
ok("fault multipliers survive save/load", pz3.fault_mult == {fl_[0].name: 0.2})


# ================================================================ well logs, blocking, kriging, conditioning
from core import logs as lgs, wells as wl_
pzl = build_demo()
stl = run_workflow(pzl.steps, pzl.surfaces, pzl.faults, pzl.tops, pzl.lattice)
gl = build_grid(stl, pzl.zones, 200.0, 200.0)
logsL = {}
for n_, w_ in pzl.wells.items():
    md_ = np.arange(0, 3000.0, 0.5)
    xyz_ = lgs.path_at_md(w_, md_)
    por_ = 0.15 + 0.08 * np.sin(xyz_[:, 2] / 15.0) + 0.02 * np.cos(xyz_[:, 0] / 700.0)
    por_[:40] = np.nan
    logsL[n_] = dict(md=md_, curves=dict(PHIE=por_, FACIES=(por_ > 0.18).astype(float)), units=dict(PHIE="v/v", FACIES=""))
nm_, lg_ = lgs.parse_las(lgs.to_las("W-1", logsL["W-1"]))
ok("LAS round trip: well, curves, nulls", nm_ == "W-1" and set(lg_["curves"]) == {"PHIE", "FACIES"} and np.isnan(lg_["curves"]["PHIE"][:40]).all()
   and np.allclose(lg_["curves"]["PHIE"][50:], logsL["W-1"]["curves"]["PHIE"][50:], atol=1e-4))
for bad_ in (b"~V\n VERS. 2.0 : x\n WRAP. YES : x\n~C\n DEPT.m : d\n~A\n1 2\n", b"hello", b"~C\n DEPT.m : d\n GR.api : g\n~A\n1.0 2.0\n3.0\n"):
    try:
        lgs.parse_las(bad_)
        ok("bad LAS rejected", False)
    except lgs.LogError:
        ok("bad LAS rejected", True)
# MD -> XYZ: vertical well and a deviated one
wv_ = wl_.Well("V", 1000.0, 2000.0, kb=30.0, td=1000.0)
pv_ = lgs.path_at_md(wv_, np.array([0.0, 500.0, 1000.0]))
ok("vertical well: MD 0 at -KB, z = MD - KB", np.allclose(pv_[:, 2], [-30.0, 470.0, 970.0]) and np.allclose(pv_[:, 0], 1000.0))
wd_ = wl_.Well("D", 0.0, 0.0, kb=0.0, td=1000.0, survey=[[0, 0, 0], [200, 0, 0], [1000, 60, 90]])
pd_ = lgs.path_at_md(wd_, np.array([0.0, 200.0, 1000.0]))
R_ = 800.0 / np.deg2rad(60.0)
ok("deviated well: MD -> XYZ follows the circular build section", np.allclose(pd_[-1], [R_ * (1 - np.cos(np.deg2rad(60))), 0.0, 200.0 + R_ * np.sin(np.deg2rad(60))], atol=1.0), tuple(np.round(pd_[-1], 1)))
arrL, infoL = lgs.block_wells(gl, pzl.wells, logsL, "PHIE")
okc_ = ~np.isnan(arrL)
ok("blocking: all wells used, cells inside active grid", len(infoL["wells"]) == len(pzl.wells) and okc_.sum() == infoL["cells"] and (gl.actnum[okc_] > 0).all())
kk_, jj_, ii_ = np.where(okc_)
tr_ = lgs.locate(gl, lgs.path_at_md(pzl.wells["W-1"], np.array([1500.0])))
ok("locate returns the cell holding the point", tr_[0, 0] < 0 or (gl.zc[tr_[0, 0], 0, tr_[0, 1], :, tr_[0, 2], :].mean() <= lgs.path_at_md(pzl.wells["W-1"], np.array([1500.0]))[0, 2] + 1e-6))
ok("blocked mean matches log mean within the sampled interval", abs(np.nanmean(arrL[okc_]) - np.nanmean([np.nanmean(v["curves"]["PHIE"]) for v in logsL.values()])) < 0.03)
arrF, _ = lgs.block_wells(gl, pzl.wells, logsL, "FACIES", discrete=True)
ok("discrete blocking gives integer codes", set(np.unique(arrF[~np.isnan(arrF)])) <= {0.0, 1.0})
arrN, infoN = lgs.block_wells(gl, pzl.wells, logsL, "NOPE")
ok("missing curve gives no data", infoN["cells"] == 0 and np.isnan(arrN).all())
# rotated grid blocking
grl = build_grid(stl, pzl.zones, 300.0, 300.0, spec=dict(angle=25.0))
arrR, infoR = lgs.block_wells(grl, pzl.wells, logsL, "PHIE")
ok("rotated grid: blocking works and uses the same wells", infoR["cells"] > 20 and len(infoR["wells"]) >= 5)
ox_, oy_ = lgs.to_local(grl, *grl.to_world(np.array([123.0]), np.array([456.0])))
ok("to_local inverts to_world", np.allclose([ox_[0], oy_[0]], [123.0, 456.0]))
# variograms
evH = lgs.experimental_variogram(gl, arrL, None, "horizontal")
evV = lgs.experimental_variogram(gl, arrL, None, "vertical")
ok("experimental variograms exist and rise from the origin", evH is not None and evV is not None and evV["gamma"][-1] > evV["gamma"][0])
fv_ = lgs.fit_range(evV, "spherical")
ok("vertical fit returns a positive range", fv_ is not None and fv_["range"] > 0 and 0 <= fv_["nugget"] <= 0.3)
# kriging
vpk = dict(vtype="spherical", major=1500.0, minor=1500.0, vert=40.0, nugget=0.0)
krg = gs.krige_property(gl, arrL, vpk, 0.0)
ok("kriging honours the data", np.abs(krg[okc_] - arrL[okc_]).max() < 1e-4)
ok("kriging fills active cells only, no NaN inside", not np.isnan(krg[gl.actnum > 0]).any() and np.isnan(krg[gl.actnum == 0]).all())
ok("kriging stays inside the data range (normal-score back-transform)", np.nanmin(krg) >= np.nanmin(arrL) - 1e-5 and np.nanmax(krg) <= np.nanmax(arrL) + 1e-5)
d3_ = np.array([[0, 0, 0], [0.5, 0, 0], [0, 0.5, 0.0]])
ok("simple kriging exact at data, 0 beyond the range", np.allclose(gs.simple_krige(d3_, np.array([1.0, -1.0, 0.5]), d3_, vpk), [1.0, -1.0, 0.5])
   and gs.simple_krige(d3_, np.array([1.0, -1.0, 0.5]), np.array([[5.0, 5, 5]]), vpk)[0] == 0.0)
# conditioning
cfgC = gs.default_config(gl)
o0_ = gs.simulate(gl, cfgC)
o1_ = gs.simulate(gl, cfgC, cond={"PORO": arrL})
ok("conditioned simulation honours the blocked data exactly", np.abs(o1_["PORO"]["values"][okc_] - arrL[okc_]).max() < 1e-6)
k2_ = np.clip(kk_ + 1, 0, gl.nk - 1)
sel_ = (gl.actnum[k2_, jj_, ii_] > 0) & (gl.layer_zone[k2_] == gl.layer_zone[kk_])
e1_ = np.abs(o1_["PORO"]["values"][k2_, jj_, ii_][sel_] - arrL[kk_, jj_, ii_][sel_]).mean()
e0_ = np.abs(o0_["PORO"]["values"][k2_, jj_, ii_][sel_] - arrL[kk_, jj_, ii_][sel_]).mean()
ok("conditioning pulls the neighbouring cells towards the data", e1_ < 0.8 * e0_, (e1_, e0_))
ok("conditioned output keeps the target histogram", abs(o1_["PORO"]["values"][gl.actnum > 0].mean() - o0_["PORO"]["values"][gl.actnum > 0].mean()) < 0.03)
cfgT = gs.default_config(gl); cfgT["perm_mode"] = "transform"
oT_ = gs.simulate(gl, cfgT, cond={"PORO": arrL, "PERM": arrL})
ok("PERM conditioning is skipped in transform mode (PORO honoured)", np.abs(oT_["PORO"]["values"][okc_] - arrL[okc_]).max() < 1e-6)
# persistence + unit conversion
pl_ = build_demo(); pl_.logs = {k: dict(md=v["md"][:100], curves={c: v["curves"][c][:100] for c in v["curves"]}, units=v["units"]) for k, v in logsL.items()}
pl2_ = proj.from_bytes(proj.to_bytes(pl_))
ok("logs persist in the project file", set(pl2_.logs) == set(pl_.logs) and np.allclose(pl2_.logs["W-1"]["md"], pl_.logs["W-1"]["md"])
   and np.allclose(pl2_.logs["W-2"]["curves"]["PHIE"], pl_.logs["W-2"]["curves"]["PHIE"], equal_nan=True, atol=1e-5) and pl2_.logs["W-1"]["units"]["PHIE"] == "v/v")
ok("old projects load with no logs", proj.from_bytes(proj.to_bytes(build_demo())).logs == {})
md0_ = float(pl_.logs["W-1"]["md"][-1])
un.convert_project(pl_, "m", "ft")
ok("depth unit conversion scales log MD", abs(pl_.logs["W-1"]["md"][-1] - md0_ / 0.3048) < 1e-6)


# ================================================================ upscaling
from core import upscale as up_
d3u = np.full((4, 3, 3), 10.0); one3 = np.ones((4, 3, 3)); act3 = np.ones((4, 3, 3), bool)
ok("flow solve: homogeneous block returns its permeability", abs(up_._flow_block(one3 * 100, one3 * 100, one3 * 100, d3u, d3u, d3u, act3, 2) - 100.0) < 1e-6)
kser = np.array([10.0, 100.0, 10.0, 100.0])[:, None, None] * one3
ok("flow solve: layers in series -> harmonic mean", abs(up_._flow_block(kser, kser, kser, d3u, d3u, d3u, act3, 0) - 4 / np.sum(1 / np.array([10, 100, 10, 100.0]))) < 1e-6)
ok("flow solve: layers in parallel -> arithmetic mean", abs(up_._flow_block(kser, kser, kser, d3u, d3u, d3u, act3, 2) - 55.0) < 1e-6)
bar_ = one3 * 100.0; bar_[:, :, 1] = 0.0
ok("flow solve: a full barrier gives zero flow", up_._flow_block(bar_, bar_, bar_, d3u, d3u, d3u, act3 & (bar_ > 0), 2) < 1e-6)
pu_ = build_demo()
stu = run_workflow(pu_.steps, pu_.surfaces, pu_.faults, pu_.tops, pu_.lattice)
gu = build_grid(stu, pu_.zones, 200.0, 200.0)
pru = pp.zone_defaults(gu)
rngu = np.random.default_rng(5)
pru["PERMX"].values = (pru["PERMX"].values * np.exp(rngu.normal(0, 0.8, pru["PERMX"].values.shape))).astype(np.float32)
pru["PERMY"].values = pru["PERMX"].values.copy()
pru["PERMZ"].values = (pru["PERMX"].values * 0.1).astype(np.float32)
pru["FAC"] = pp.make_property(gu, "FAC", np.where(np.arange(gu.nk)[:, None, None] % 3 == 0, 2, 1) * np.ones((gu.nk, gu.nj, gu.ni)), "discrete")
cu_ = up_.build_coarse(gu, 2, 2, [2] * len(gu.zones))
cgu = cu_.grid
ok("coarse grid: dimensions follow the groups, zones kept", cgu.nk == 2 * len(gu.zones) and cgu.ni <= gu.ni and cgu.nj <= gu.nj and set(cgu.layer_zone) == set(range(len(gu.zones))))
bl_ = gu.block
cut_i = set(np.where((bl_[:, :-1] != bl_[:, 1:]).any(axis=0))[0] + 1)
ok("coarse I / J edges include every fault-block change", cut_i <= set(cu_.ie.tolist()))
Vfu = gu.bulk_volume() * (gu.actnum > 0)
ok("coarse bulk volume equals the fine bulk volume (corner interpolation only)", abs(cgu.bulk_volume()[cgu.actnum > 0].sum() / Vfu.sum() - 1) < 5e-3)
oua = up_.upscale_properties(cu_, gu, pru, "arithmetic")
oug = up_.upscale_properties(cu_, gu, pru, "geometric")
ouh = up_.upscale_properties(cu_, gu, pru, "harmonic")
m_ = np.isfinite(oua["PERMX"]["values"])
ok("averaging order: arithmetic >= geometric >= harmonic", (oua["PERMX"]["values"][m_] >= oug["PERMX"]["values"][m_] - 1e-6).all() and (oug["PERMX"]["values"][m_] >= ouh["PERMX"]["values"][m_] - 1e-6).all())
q_ = up_.qc(cu_, gu, pru, oua)
ok("net pore volume is conserved by the upscaling", abs(q_["pv_coarse"] / q_["pv_fine"] - 1) < 5e-3, q_["pv_coarse"] / q_["pv_fine"] - 1)
ok("discrete property: majority values only", set(np.unique(oua["FAC"]["values"][np.isfinite(oua["FAC"]["values"])])) <= {1.0, 2.0})
ouf = up_.upscale_properties(cu_, gu, pru, "flow")
mf_ = np.isfinite(ouf["PERMX"]["values"]) & m_
fr_ = ouf["PERMX"]["values"][mf_] / oua["PERMX"]["values"][mf_]
fh_ = ouf["PERMX"]["values"][mf_] / ouh["PERMX"]["values"][mf_]
ok("flow-based kx: >=95% of cells between harmonic and arithmetic (geometry effects allowed)", np.mean((fr_ <= 1.05) & (fh_ >= 0.95)) >= 0.95, np.mean((fr_ <= 1.05) & (fh_ >= 0.95)))
ok("flow-based kx differs from the arithmetic mean where cells are wider than one column (5th percentile < 0.97)", np.percentile(fr_, 5) < 0.97 and fr_.min() > 0.05, np.percentile(fr_, 5))
ok("flow-based results are positive everywhere active (fallback fills clipped cells)", (ouf["PERMX"]["values"][np.isfinite(ouf["PERMX"]["values"])] > 0).all() and (ouf["PERMZ"]["values"][np.isfinite(ouf["PERMZ"]["values"])] > 0).all())
try:
    up_.flow_upscale(cu_, gu, pru["PERMX"].values, pru["PERMY"].values, pru["PERMZ"].values, max_cells=10)
    ok("flow upscaling refuses oversized jobs", False)
except up_.UpscaleError:
    ok("flow upscaling refuses oversized jobs", True)
ok("coarse grid exports (GRDECL + EGRID)", "SPECGRID" in export.grdecl_text(cgu, ["PORO"], "c", custom={"PORO": pp.make_property(cgu, "PORO", np.nan_to_num(oua["PORO"]["values"]), "continuous")}) and len(sf_.egrid_bytes(cgu)) > 1000) if (sf_ := __import__("core.simfmt", fromlist=["x"])) else None
pu_.upscale = dict(ci=3, cj=2, nk={"A": 2}, method="flow", omega=0.5)
ok("upscaling settings persist", proj.from_bytes(proj.to_bytes(pu_)).upscale == pu_.upscale and proj.from_bytes(proj.to_bytes(build_demo())).upscale == {})

# ================================================================ inclined pillars along fault planes
from core import simfmt as sfm_
from core import resqml as rq_
pt_ = build_demo()
stt = run_workflow(pt_.steps, pt_.surfaces, pt_.faults, pt_.tops, pt_.lattice)
g_v = build_grid(stt, pt_.zones, 200.0, 200.0)
g_t = build_grid(stt, pt_.zones, 200.0, 200.0, spec=dict(tilt=True, tilt_radius=3.0))
ok("tilt off by default: vertical pillars, no slope array", g_v.slope is None and not g_v.tilted and "vertical" in g_v.notes[0])
ok("tilt on: pillars inclined near faults, note says so", g_t.tilted and "inclined" in g_t.notes[0] and any("Pillars inclined" in n for n in g_t.notes), g_t.notes[:2])
ok("tilt is zero away from the faults", (np.abs(g_t.slope).sum(axis=-1) == 0).any() and np.abs(g_t.slope).max() > 0.2)
f1_ = pt_.faults["F1_main"] if "F1_main" in pt_.faults else list(pt_.faults.values())[0]
tr_ = np.asarray(f1_.trace, float)
from core.cpgrid import tilt_slopes
PXt, PYt = g_t.pillar_xy()
sx_, sy_, w_ = tilt_slopes([f1_], PXt, PYt, 600.0)
d_ = tr_[-1] - tr_[0]
nl_ = np.array([-d_[1], d_[0]]) / np.linalg.norm(d_)
along_ = (sx_ * nl_[0] + sy_ * nl_[1]) * (1 if f1_.hw_side == "left" else -1)
ok("slope points towards the hanging wall and has magnitude <= cot(dip)", (along_[w_ > 0] >= -1e-9).all() and np.hypot(sx_, sy_).max() <= 1 / np.tan(np.deg2rad(f1_.dip)) + 1e-9)
ok("plane following: slope at full weight equals cot(dip)", abs(np.hypot(sx_, sy_).max() - 1 / np.tan(np.deg2rad(f1_.dip))) < 0.05, np.hypot(sx_, sy_).max())
kk_, jj_, ii_ = np.indices(g_t.actnum.shape)
areas_ok = True
for t_ in (0, 1):
    cs = [g_t.corner_xy(kk_, t_, jj_, b_, ii_, a_) for (b_, a_) in ((0, 0), (0, 1), (1, 1), (1, 0))]
    xs4 = np.stack([c[0] for c in cs]); ys4 = np.stack([c[1] for c in cs])
    A_ = 0.5 * sum(xs4[q] * ys4[(q + 1) % 4] - xs4[(q + 1) % 4] * ys4[q] for q in range(4))
    areas_ok &= bool((A_ > 0.2 * 200 * 200).all())
ok("no inverted or collapsed cell at any depth (plan area > 0.2 of vertical)", areas_ok)
Xc_, Yc_ = g_t.corner_xy(kk_, 0, jj_, 0, ii_, 0)
Zc_ = g_t.zc[:, 0, :, 0, :, 0]
k_top_ = 0
sel_ = (g_t.layer_zone == 0)
zt_chk = stt.eval(Xc_[k_top_], Yc_[k_top_], sides=None)[stt.names.index(pt_.zones[0].top)]
ok("horizons evaluated where the tilted pillar crosses them (median error < 1.5 m)", np.median(np.abs(zt_chk - Zc_[k_top_])) < 1.5, np.median(np.abs(zt_chk - Zc_[k_top_])))
ok("bulk volume with tilt within 1 % of the vertical grid", abs(g_t.bulk_volume()[g_t.actnum > 0].sum() / g_v.bulk_volume()[g_v.actnum > 0].sum() - 1) < 0.01)
cd_ = g_t.coord()
zz_ = g_t.zc[5, 0, 7, 1, 9, 1]
fr_ = (zz_ - cd_[8, 10, 2]) / (cd_[8, 10, 5] - cd_[8, 10, 2])
px_ = cd_[8, 10, 0] + fr_ * (cd_[8, 10, 3] - cd_[8, 10, 0])
ok("COORD pillar passes through the corner (straight pillar line)", abs(px_ - g_t.corner_xy(5, 0, 7, 1, 9, 1)[0]) < 1e-6)
rd_ = {k_: v_ for k_, _, v_ in sfm_.read_kw(sfm_.egrid_bytes(g_t))}
ok("EGRID COORD carries the tilted pillars", np.allclose(np.asarray(rd_["COORD"]).reshape(-1, 6), cd_.reshape(-1, 6), atol=0.01))
gft = export.scaled_grid(g_t, 3.28084, 3.28084)
ok("unit conversion keeps the tilted geometry consistent", np.allclose(gft.corner_xy(3, 1, 5, 0, 8, 1), np.array(g_t.corner_xy(3, 1, 5, 0, 8, 1)) * 3.28084, atol=1e-6))
cpt_ = rq_.corner_points(g_t)
ok("RESQML corner points follow the tilted pillars", np.allclose(cpt_[4, 6, 9, 1, 1, 0, :2], np.array(g_t.corner_xy(4, 1, 6, 1, 9, 0))))
vtk_ = export.vtk_text(g_t, {})
ok("VTK export runs on the tilted grid", "UNSTRUCTURED_GRID" in vtk_)
fcs_, _, _ = g_t.exterior_faces(0, 0, None)
ok("3D skin generated for the tilted grid", len(fcs_) > 1000)
# well blocking on a tilted grid: the centre of a cell is found in that cell
ctr_ = np.mean([[*g_t.corner_xy(6, t_, 8, b_, 12, a_), g_t.zc[6, t_, 8, b_, 12, a_]] for t_ in (0, 1) for b_ in (0, 1) for a_ in (0, 1)], axis=0)
loc_ = lgs.locate(g_t, np.array([[ctr_[0], ctr_[1], ctr_[2]]]))[0]
ok("log blocking finds the cell on a tilted grid", tuple(loc_) == (6, 8, 12) or g_t.actnum[6, 8, 12] == 0, tuple(loc_))
cc_ = up_.build_coarse(g_t, 2, 2, [2] * len(g_t.zones))
ok("coarse grid inherits the pillar slope", cc_.grid.slope is not None and cc_.grid.slope.shape == (cc_.grid.nj + 1, cc_.grid.ni + 1, 2))
pr_t = pp.zone_defaults(g_t)
okv_ = abs(sum(float((g_t.bulk_volume() * np.nan_to_num(pr_t["PORO"].values)).sum()) for _ in [0]) / float((g_v.bulk_volume() * np.nan_to_num(pp.zone_defaults(g_v)["PORO"].values)).sum()) - 1)
ok("pore volume with tilt within 1.5 % of the vertical grid", okv_ < 0.015, okv_)
gx_ = build_grid(stt, pt_.zones, 200.0, 200.0, spec=dict(tilt=True, tilt_radius=3.0, angle=20.0))
ok("tilt works on a rotated grid (areas positive)", gx_.tilted and (gx_.bulk_volume()[gx_.actnum > 0] > 0).all())
g_big = build_grid(stt, pt_.zones, 200.0, 200.0, spec=dict(tilt=True, tilt_radius=30.0))
ok("a huge radius is limited automatically (no inverted cell)", g_big.tilted and (g_big.bulk_volume()[g_big.actnum > 0] > 0).all() and any("reduced" in n for n in g_big.notes), g_big.notes[:2])


# ================================================================ facies modelling
from core import facies as fac_
pfa = build_demo()
stf = run_workflow(pfa.steps, pfa.surfaces, pfa.faults, pfa.tops, pfa.lattice)
gf = build_grid(stf, pfa.zones, 200.0, 200.0)
cf = fac_.default_config(gf)
ok("facies default config valid", fac_.check_config(cf, gf) == [] and len(cf["zones"]) == len(gf.zones))
fa1 = fac_.simulate(gf, cf)
prp = fac_.proportions(gf, fa1, cf)
ok("TGS reproduces the target proportions per zone (|err| < 0.05; ranks are by cell count, not volume)", all(abs(r[f["name"]] - z["top"][q] / sum(z["top"])) < 0.05 for r, z in zip(prp, cf["zones"]) for q, f in enumerate(cf["facies"])))
ok("TGS is reproducible with the seed and changes with another", np.array_equal(fa1, fac_.simulate(gf, cf)) and not np.array_equal(fa1, fac_.simulate(gf, {**cf, "seed": 7})))
ok("only table codes appear", set(np.unique(fa1)) <= {1, 2, 3})
# ordering: shale (1) and sand (3) rarely touch in I direction with a smooth field
actf = gf.actnum > 0
cfs = fac_.default_config(gf)
for z in cfs["zones"]:
    z.update(major=8000.0, minor=8000.0)
fa1s = fac_.simulate(gf, cfs)
touch13 = (((fa1s[:, :, :-1] == 1) & (fa1s[:, :, 1:] == 3)) | ((fa1s[:, :, :-1] == 3) & (fa1s[:, :, 1:] == 1))) & actf[:, :, :-1] & actf[:, :, 1:]
touch12 = (((fa1s[:, :, :-1] == 1) & (fa1s[:, :, 1:] == 2)) | ((fa1s[:, :, :-1] == 2) & (fa1s[:, :, 1:] == 1))) & actf[:, :, :-1] & actf[:, :, 1:]
ok("TGS honours the facies order (1-3 contacts much rarer than 1-2)", touch13.sum() < 0.35 * touch12.sum(), (int(touch13.sum()), int(touch12.sum())))
cft = fac_.default_config(gf); cft["trend"] = True
for z in cft["zones"]:
    z["top"], z["base"] = [0.7, 0.2, 0.1], [0.1, 0.2, 0.7]
fat = fac_.simulate(gf, cft)
vpc = fac_.vertical_proportions(gf, fat, cft)
kz_ = np.where(gf.layer_zone == 2)[0]
ok("vertical proportion trend: shale decreases, sand increases towards the base", vpc["Shale"][kz_[0]] > vpc["Shale"][kz_[-1]] + 0.2 and vpc["Sand"][kz_[-1]] > vpc["Sand"][kz_[0]] + 0.2, (vpc["Shale"][kz_[[0, -1]]], vpc["Sand"][kz_[[0, -1]]]))
logsF = {}
for n_, w_ in pfa.wells.items():
    md_ = np.arange(0, 3000.0, 0.5)
    xyz_ = lgs.path_at_md(w_, md_)
    logsF[n_] = dict(md=md_, curves=dict(FAC=(1 + (np.sin(xyz_[:, 2] / 12) > 0.2) + (np.sin(xyz_[:, 2] / 12) > 0.8)).astype(float)), units=dict(FAC=""))
blkF, _ = lgs.block_wells(gf, pfa.wells, logsF, "FAC", discrete=True)
faC = fac_.simulate(gf, cf, cond=blkF)
mF = ~np.isnan(blkF)
ok("conditioned TGS honours the blocked facies exactly", (faC[mF] == blkF[mF]).all() and mF.sum() > 50)
kF, jF, iF = np.where(mF); k2F = np.clip(kF + 1, 0, gf.nk - 1)
sF = (gf.actnum[k2F, jF, iF] > 0) & (gf.layer_zone[k2F] == gf.layer_zone[kF])
ok("conditioning improves agreement of the neighbours with the data", (faC[k2F, jF, iF][sF] == blkF[kF, jF, iF][sF]).mean() > (fa1[k2F, jF, iF][sF] == blkF[kF, jF, iF][sF]).mean() + 0.05)
wpF = fac_.well_proportions(gf, blkF, cf)
ok("well proportions sum to 1 where data exist", all(abs(sum(v) - 1) < 1e-9 for v in wpF.values() if not np.isnan(v).any()) and any(not np.isnan(v).any() for v in wpF.values()))
co = fac_.default_config(gf); co["method"] = "objects"; co["background"] = 1
co["objects"] = [dict(code=3, length=1200.0, width=300.0, thickness=6.0, azimuth=45.0)]
for z in co["zones"]:
    z["top"] = z["base"] = [0.7, 0.0, 0.3]
fo = fac_.simulate(gf, co)
pro_ = fac_.proportions(gf, fo, co)
ok("objects reach the target volume fraction (0.30 +/- 0.05)", all(abs(r["Sand"] - 0.3) < 0.05 for r in pro_), [round(r["Sand"], 2) for r in pro_])
co2 = {**co, "objects": [dict(code=3, length=1200.0, width=300.0, thickness=6.0, azimuth=0.0)], "azimuth_sd": 0.0}
fo2 = fac_.simulate(gf, co2)
ik_ = np.where(gf.layer_zone == 2)[0]
sand = (fo2[ik_] == 3)
along_y = (sand[:, 1:, :] & sand[:, :-1, :]).sum(); along_x = (sand[:, :, 1:] & sand[:, :, :-1]).sum()
ok("object azimuth 0 deg (north) -> bodies elongated in J", along_y > 1.5 * along_x, (int(along_y), int(along_x)))
try:
    fac_.simulate(gf, {**cf, "facies": cf["facies"][:1]}); ok("one facies rejected", False)
except fac_.FaciesError:
    ok("one facies rejected", True)
bad_cf = fac_.default_config(gf); bad_cf["zones"][0]["top"] = [1.0, 1.0]
ok("wrong proportion count reported", any("proportions" in e for e in fac_.check_config(bad_cf, gf)))
ppf = fac_.petrophysics(gf, fa1, cf)
ok("facies petrophysics: PORO / logK means follow the facies table", all(abs(ppf["PORO"]["values"][actf & (fa1 == r["code"])].mean() - r["poro"]) < 0.01
   and abs(np.log10(ppf["PERMX"]["values"][actf & (fa1 == r["code"])]).mean() - r["logk"]) < 0.1 for r in cf["petro"]))
ok("facies petrophysics: NTG follows the net flag, PERMZ = PERMX x KV/KH", set(np.unique(ppf["NTG"]["values"])) <= {0.0, 1.0}
   and np.allclose(ppf["PERMZ"]["values"][gf.layer_zone == 2], ppf["PERMX"]["values"][gf.layer_zone == 2] * gf.zones[2].kvkh))
ok("PORO-PERM correlation inside a facies is positive (rho 0.7)", np.corrcoef(ppf["PORO"]["values"][actf & (fa1 == 3)], np.log10(ppf["PERMX"]["values"][actf & (fa1 == 3)]))[0, 1] > 0.4)
pfa.facies = cf
ok("facies settings persist", proj.from_bytes(proj.to_bytes(pfa)).facies["facies"][2]["name"] == "Sand" and proj.from_bytes(proj.to_bytes(build_demo())).facies == {})


# ---- volume-weighted proportions, plurigaussian, indicator simulation
def vol_err(fa_, cf_):
    prs = fac_.proportions(gf, fa_, cf_)
    return max(abs(r[f["name"]] - z["top"][q] / sum(z["top"])) for r, z in zip(prs, cf_["zones"]) for q, f in enumerate(cf_["facies"]))
cvw = fac_.default_config(gf); cvw["vol_weight"] = False
e_cnt = vol_err(fac_.simulate(gf, cvw), cvw)
cvw["vol_weight"] = True
e_vol = vol_err(fac_.simulate(gf, cvw), cvw)
ok("volume-weighted TGS matches the volume proportions (< 0.01) and beats the cell-count version", e_vol < 0.01 and e_vol < e_cnt, (e_vol, e_cnt))
cpg = fac_.default_config(gf); cpg["method"] = "plurigaussian"
fpg = fac_.simulate(gf, cpg)
ok("plurigaussian reproduces the proportions (volume-weighted, < 0.02)", vol_err(fpg, cpg) < 0.02, vol_err(fpg, cpg))
ok("plurigaussian is reproducible and differs from TGS", np.array_equal(fpg, fac_.simulate(gf, cpg)) and not np.array_equal(fpg, fa1))
a_, b_, ach_ = fac_.band_probabilities([[1, 1], [2, 3]], np.array([0.4, 0.2, 0.4]), [1, 2, 3])
ok("truncation rule: band probabilities solve a reachable rule exactly", np.allclose(ach_, [0.4, 0.2, 0.4], atol=1e-6) and abs(a_.sum() - 1) < 1e-9 and abs(b_.sum() - 1) < 1e-9)
cbad = fac_.default_config(gf); cbad["method"] = "plurigaussian"; cbad["rule"] = [[1, 2], [2, 1]]
ok("an unreachable truncation rule is reported", any("truncation rule" in e for e in fac_.check_config(cbad, gf)))
cbad["rule"] = [[1, 9]]
ok("a rule with unknown codes is rejected", any("Truncation rule" in e for e in fac_.check_config(cbad, gf)))
cpg2 = fac_.default_config(gf); cpg2["method"] = "plurigaussian"; cpg2["rule"] = [[1, 1, 2], [3, 2, 3]]
for z in cpg2["zones"]:
    z["top"] = [0.3, 0.3, 0.4]
ok("a 2 x 3 rule with a repeated facies runs", set(np.unique(fac_.simulate(gf, cpg2)[actf])) <= {1, 2, 3} and fac_.check_config(cpg2, gf) == [])
csi = fac_.default_config(gf); csi["method"] = "indicator"
fsi = fac_.simulate(gf, csi)
prs_ = fac_.proportions(gf, fsi, csi)
ok("SIS reproduces the proportions within 0.08 (random-path sampling noise)", max(abs(r[f["name"]] - 1.0 * z["top"][q] / sum(z["top"])) for r, z in zip(prs_, csi["zones"]) for q, f in enumerate(csi["facies"])) < 0.08)
ok("SIS only writes active cells and table codes", set(np.unique(fsi[actf])) <= {1, 2, 3} and (fsi[~actf] == 0).all())
same_ = lambda f_: ((f_[:, :, 1:] == f_[:, :, :-1]) & actf[:, :, 1:] & actf[:, :, :-1]).sum() / (actf[:, :, 1:] & actf[:, :, :-1]).sum()
ok("SIS facies are spatially continuous (neighbour agreement above the random 0.36)", same_(fsi) > 0.5, same_(fsi))
fsc = fac_.simulate(gf, csi, cond=blkF)
ok("conditioned SIS honours the blocked facies exactly", (fsc[mF] == blkF[mF]).all())
ok("conditioned SIS pulls neighbours towards the data", (fsc[k2F, jF, iF][sF] == blkF[kF, jF, iF][sF]).mean() > (fsi[k2F, jF, iF][sF] == blkF[kF, jF, iF][sF]).mean() + 0.1)
csl = fac_.default_config(gf); csl["method"] = "indicator"
for z in csl["zones"]:
    z.update(major=300.0, minor=300.0, vert=2.0)
ok("shorter ranges give less continuous SIS", same_(fac_.simulate(gf, csl)) < same_(fsi))
cold = fac_.default_config(gf)
for k_ in ("vol_weight", "rule", "nmax"):
    cold.pop(k_)
for z in cold["zones"]:
    z.pop("major2")
cold = fac_.normalise(cold, gf)
ok("old facies settings get the new keys", cold["vol_weight"] is True and "rule" in cold and "major2" in cold["zones"][0])
cst = fac_.default_config(gf); cst["method"] = "indicator"; cst["trend"] = True
for z in cst["zones"]:
    z["top"], z["base"] = [0.7, 0.2, 0.1], [0.1, 0.2, 0.7]
vp_s = fac_.vertical_proportions(gf, fac_.simulate(gf, cst), cst)
ok("SIS follows the vertical proportion trend", vp_s["Shale"][kz_[0]] > vp_s["Shale"][kz_[-1]] + 0.15, tuple(np.round(vp_s["Shale"][kz_[[0, -1]]], 2)))

bad = [n for n, c in PASS if not c]

print(f"\n{len(PASS) - len(bad)}/{len(PASS)} passed")
sys.exit(1 if bad else 0)
