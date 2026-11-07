"""Headless run of every page through a fake Streamlit (real Streamlit is not installed here)."""
import json, os, sys, traceback
from contextlib import contextmanager
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fake_streamlit as fs
fs.install()

from ui import state as S
from views import home, surfaces, faults, tops, workflow, zones, grid, export, polygons, wells, viewer
from core import io_surfaces, project as pj
from core.surface import Geometry, synthetic_surface

results = []


def ok(name, cond, info=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))


def page(fn, **ctl):
    fs.MESSAGES.clear()
    try:
        fs.run(fn)
        return True
    except Exception:
        traceback.print_exc()
        return False


class F:
    def __init__(self, name, data):
        self.name, self._d, self.size = name, data, len(data)

    def getvalue(self):
        return self._d


def errors():
    return [m for l, m in fs.MESSAGES if l == "error"]


# ---------------------------------------------------------------- empty project renders
shared = dict(type="faults", _id="eb7327c8")
repair = pj.Project()
repair.steps = [shared, shared, dict(shared), dict(type="faults"), dict(type="faults", _id="")]
S.ensure_step_ids(repair)
ids = [s["_id"] for s in repair.steps]
ok("step IDs repair aliased, duplicate and missing IDs", len(set(ids)) == len(ids) and ids[0] == "eb7327c8")
ok("repeated step dictionaries become independent", repair.steps[0] is not repair.steps[1])
S.ensure_step_ids(repair)
ok("repaired step IDs stay stable on rerun", ids == [s["_id"] for s in repair.steps])
repair = pj.from_bytes(pj.to_bytes(repair))
S.ensure_step_ids(repair)
ok("repaired step IDs survive save/load", ids == [s["_id"] for s in repair.steps])

ok("home renders (empty)", page(home.render))
for name, fn in [("surfaces", surfaces.render), ("faults", faults.render), ("tops", tops.render), ("workflow", workflow.render),
                 ("zones", zones.render), ("grid", grid.render), ("export", export.render)]:
    ok(f"{name} renders (empty project)", page(fn))

# ---------------------------------------------------------------- demo
fs.PRESS.add("Open demo project")
ok("open demo", page(home.render) and len(S.proj().surfaces) == 4 and len(S.proj().faults) == 2)
p = S.proj()
ok("demo workflow steps are independent", p.steps[0] is not p.steps[-1])
original_button = fs.button
button_keys = set()


def unique_button(label, key=None, **kw):
    if key is not None:
        if key in button_keys:
            raise AssertionError(f"Duplicate button key: {key}")
        button_keys.add(key)
    return original_button(label, key=key, **kw)


fs.PRESS.clear()
sys.modules["streamlit"].button = unique_button
try:
    ok("demo workflow renders with unique button keys", page(workflow.render))
finally:
    sys.modules["streamlit"].button = original_button

ok("home renders (demo)", page(home.render))

# Workflow step editors use expanders; rendering map-extension settings inside
# one must not create another Streamlit expander.
st_module = sys.modules["streamlit"]
original_expander = st_module.expander
expander_depth = 0


@contextmanager
def checked_expander(label, expanded=False):
    global expander_depth
    if expander_depth:
        raise AssertionError("nested Streamlit expanders are not supported")
    expander_depth += 1
    try:
        with original_expander(label, expanded=expanded):
            yield
    finally:
        expander_depth -= 1


st_module.expander = checked_expander
try:
    with st_module.expander("workflow step"):
        workflow.step_form("surface", dict(horizon="Test", surface="Top_Reservoir"), "nested_test", p)
    ok("surface workflow step renders without nested expanders", True)
except Exception as exc:
    ok("surface workflow step renders without nested expanders", False, str(exc))
finally:
    st_module.expander = original_expander

# library / import / synthetic
ok("surfaces page (library, import, digitize, synthetic)", page(surfaces.render) and not errors(), errors())
surface_before = p.surfaces["Top_Reservoir"].z.copy()
fs.OVERRIDES.update({
    "lib_dup_source": "Top_Reservoir",
    "lib_dup_name_Top_Reservoir": "Top_Reservoir_shifted",
    "lib_dup_value_Top_Reservoir_add": 5.0,
})
fs.PRESS.add("Create duplicate")
ok("duplicate surface with additive scalar",
   page(surfaces.render) and "Top_Reservoir_shifted" in p.surfaces
   and np.allclose(p.surfaces["Top_Reservoir_shifted"].z, surface_before + 5.0, equal_nan=True)
   and np.array_equal(p.surfaces["Top_Reservoir"].z, surface_before, equal_nan=True))
fs.OVERRIDES.update({
    "lib_dup_name_Top_Reservoir": "Top_Reservoir_scaled",
    "lib_dup_op": "Multiply by factor",
    "lib_dup_value_Top_Reservoir_multiply": 1.01,
})
fs.PRESS.add("Create duplicate")
ok("duplicate surface with multiplicative scalar",
   page(surfaces.render) and "Top_Reservoir_scaled" in p.surfaces
   and np.allclose(p.surfaces["Top_Reservoir_scaled"].z, surface_before * 1.01, equal_nan=True))
fs.OVERRIDES["del_sel"] = "Top_Reservoir"
fs.OVERRIDES["delete_surface_confirm_Top_Reservoir"] = True
fs.PRESS.add("Delete surface")
ok("deleting a surface used by a workflow step is blocked",
   page(surfaces.render) and "Top_Reservoir" in p.surfaces
   and any(level == "warning" and "used by workflow" in message for level, message in fs.MESSAGES))
fs.PRESS.discard("Delete surface")
fs.OVERRIDES["del_sel"] = "Top_Reservoir_shifted"
fs.OVERRIDES["delete_surface_confirm_Top_Reservoir_shifted"] = True
fs.PRESS.add("Delete surface")
ok("confirmed deletion removes an unused surface",
   page(surfaces.render) and "Top_Reservoir_shifted" not in p.surfaces
   and "Top_Reservoir_shifted" not in p.raw and "Top_Reservoir_shifted" not in p.filters)
fs.OVERRIDES.clear()
asc = io_surfaces.write_esri_ascii(p.surfaces["Top_Reservoir"].resample_to(Geometry(450000, 6700000, 200, 200, 41, 31)))
fs.OVERRIDES["surf_up"] = [F("my_map.asc", asc),
                           F("pts.xyz", "\n".join(f"{450000 + 100 * i},{6700000 + 100 * j},{2000 - i - j}" for i in range(0, 80, 4) for j in range(0, 60, 4)).encode())]
fs.PRESS.update(["add_my_map.asc", "grid_pts.xyz"])
fs.DOWNLOADS.clear()
ok("import ASCII + grid XYZ", page(surfaces.render) and "my_map" in p.surfaces and "pts" in p.surfaces, errors())
ok("imported and gridded surfaces have save buttons",
   {"my_map.gri", "pts.gri"} <= {download[1] for download in fs.DOWNLOADS})
fs.OVERRIDES.pop("surf_up")
fs.PRESS.add("Create surface")
fs.OVERRIDES["syn_name"] = "Syn1"
fs.DOWNLOADS.clear()
ok("synthetic surface", page(surfaces.render) and "Syn1" in p.surfaces)
ok("synthetic surface can be saved immediately", any(download[1] == "Syn1.gri" for download in fs.DOWNLOADS))
fs.DOWNLOADS.clear()
ok("synthetic surface save persists across reruns", page(surfaces.render)
   and any(download[1] == "Syn1.gri" for download in fs.DOWNLOADS))
fs.OVERRIDES.pop("syn_name")

# digitizer round trip
dig = dict(kind="digitize", nonce=1,
           contours=[dict(z=2000.0, pts=[[450500, 6701000], [453000, 6701500], [456000, 6701000]]),
                     dict(z=1900.0, pts=[[451000, 6703000], [453000, 6704000], [455000, 6703000]]),
                     dict(z=2100.0, pts=[[450500, 6705500], [454000, 6705800], [457000, 6705500]])],
           points=[[453000.0, 6703300.0, 1850.0]],
           faults=[dict(name="Fault_1", pts=[[452000, 6700500], [454000, 6705500]])], calib=None)
fs.COMPONENT_VALUES["geomodel_map_editor"] = dig
ok("digitizer value stored", page(surfaces.render) and len(p.digitized["contours"]) == 3 and len(p.digitized["faults"]) == 1)
fs.PRESS.update(["Grid digitized data", "Add fault traces"])
fs.OVERRIDES["dig_name"] = "Dig_map"
fs.DOWNLOADS.clear()
ok("grid digitized contours -> surface", page(surfaces.render) and "Dig_map" in p.surfaces, errors())
ok("digitized surface can be saved immediately", any(download[1] == "Dig_map.gri" for download in fs.DOWNLOADS))
fs.OVERRIDES["digitized_save_format"] = "IRAP ASCII"
fs.DOWNLOADS.clear()
ok("digitized surface save persists and format can change", page(surfaces.render)
   and any(download[1] == "Dig_map.irap" for download in fs.DOWNLOADS))
fs.OVERRIDES.pop("digitized_save_format")
ok("digitized contour depths produce a varying map", np.ptp(p.surfaces["Dig_map"].z) > 50)
dig_spec = [payload["spec"] for kind, payload in fs.CALLS if kind == "component:geomodel_plotly_view" and payload.get("key") == S.k("digprev")][-1]
ok("digitized map preview includes boundary", any(t.get("name") == p.boundary + " (boundary)" for t in dig_spec["data"]))
fs.OVERRIDES["dig_boundary"] = False
ok("digitized preview persists when boundary is toggled", page(lambda: surfaces._digitize(p)))
dig_spec = [payload["spec"] for kind, payload in fs.CALLS if kind == "component:geomodel_plotly_view" and payload.get("key") == S.k("digprev")][-1]
ok("digitized preview boundary can be hidden", not any(t.get("name") == p.boundary + " (boundary)" for t in dig_spec["data"]))
fs.OVERRIDES.pop("dig_boundary")
saved_dig = p.digitized
p.digitized = dict(contours=[dict(z=2000.0, pts=[[451000, 6701000], [452000, 6702000], [453000, 6703000]])], points=[], faults=[], calib=None)
fs.COMPONENT_VALUES.pop("geomodel_map_editor")
ok("constant-depth digitizing displays an explicit warning", page(lambda: surfaces._digitize(p))
   and any(level == "warning" and "constant map" in message for level, message in fs.MESSAGES))
p.digitized = saved_dig
ok("digitized fault trace added as fault", any(n.startswith("Fault_1") for n in p.faults), list(p.faults))
fs.OVERRIDES.pop("dig_name")

# faults page
ok("fault designer initializes with backdrop", page(faults.render) and not errors(), errors())
fault_grid = [payload["grid"] for kind, payload in fs.CALLS
              if kind == "component:geomodel_map_editor" and payload.get("mode") == "faults"][-1]
ok("fault backdrop reaches JavaScript as flat numeric depths",
   len(fault_grid["z"]) == fault_grid["nrow"] * fault_grid["ncol"]
   and all(z is None or isinstance(z, (float, int)) for z in fault_grid["z"]))
from ui.components import map_editor
editor_grid = dict(x0=0, y0=0, dx=1, dy=1, ncol=2, nrow=2, z=np.array([[1000, np.nan], [1020, 1030]]),
                   zmin=1000, zmax=1030)
for mode in ("faults", "polygons", "fences"):
    map_editor(mode, key="test_grid_" + mode, grid=editor_grid)
    sent_grid = fs.CALLS[-1][1]["grid"]
    ok(f"{mode} grid conversion preserves row order and undefined nodes", sent_grid["z"] == [1000.0, None, 1020.0, 1030.0])
ok("map editor leaves input grid unchanged", editor_grid["z"].shape == (2, 2) and np.isnan(editor_grid["z"][0, 1]))
try:
    map_editor("faults", key="invalid_grid", grid=dict(editor_grid, z=[1, 2, 3]))
    ok("map editor rejects malformed grid depths", False)
except ValueError as e:
    ok("map editor rejects malformed grid depths", "grid depths must have shape" in str(e))
fs.COMPONENT_VALUES["geomodel_map_editor"] = dict(kind="faults", nonce=7, faults=[
    dict(name="FA", trace=[[452000, 6701000], [455000, 6704500]], ftype="normal", throw=55, dip=60, hw_side="right", profile="plateau", drag=200, growth=0, zref=2000, color="#D7263D"),
    dict(name="FB", trace=[[453000, 6700500], [455500, 6702500]], ftype="reverse", throw=30, dip=70, hw_side="left", profile="elliptical", drag=250, growth=1.5, zref=2050, color="#2E294E")])
ok("fault editor value applied", page(faults.render) and set(p.faults) == {"FA", "FB"} and p.faults["FA"].hw_side == "right", list(p.faults))
fs.COMPONENT_VALUES.pop("geomodel_map_editor")
fs.PRESS.add("Set zref")
ok("faults page extras (preview, zref)", page(faults.render) and not errors(), errors())
# restore demo faults for the rest
from core.demo import build_demo
d = build_demo()
p.faults = dict(d.faults)
p.steps = [dict(s) for s in d.steps]
p.zones = list(d.zones)
p.tops = d.tops.copy()
p.structure = None

# tops
csv = b"Well,X,Y,Horizon,Z_TVDSS\nA-1,452000,6703000,Top_Reservoir,2010.5\nA-1,452000,6703000,Base_Reservoir,2140.0\n"
fs.OVERRIDES["tops_up"] = F("tops.csv", csv)
ok("tops import", page(tops.render) and len(p.tops) == 2, p.tops.shape)
fs.OVERRIDES.pop("tops_up")
p.tops = d.tops.copy()
ok("tops page (with data)", page(tops.render))

# workflow
fs.PRESS.add("Run workflow")
ok("workflow runs from UI", page(workflow.render) and p.structure is not None and not errors(), errors())
ok("workflow results render", page(workflow.render) and not errors(), errors())
n0 = len(p.steps)
fs.OVERRIDES["new_kind"] = "smooth"
fs.PRESS.add("add_step")
ok("add smooth step", page(workflow.render) and len(p.steps) == n0 + 1, [s["type"] for s in p.steps][-3:])
fs.OVERRIDES["new_kind"] = "isochore"
fs.OVERRIDES["new_isochore_h"] = "Extra_below"
fs.PRESS.add("add_step")
ok("add isochore step", page(workflow.render) and p.steps[-1]["type"] == "isochore" and p.steps[-1]["horizon"] == "Extra_below", p.steps[-1])
fs.OVERRIDES.pop("new_kind"); fs.OVERRIDES.pop("new_isochore_h")
fs.PRESS.add("dn")
page(workflow.render)
fs.PRESS.add("rm")
n1 = len(p.steps)
page(workflow.render)
ok("move/remove step buttons work", len(p.steps) == n1 - 1)
# restore the demo workflow so zones still match
p.steps = [dict(s) for s in d.steps]
fs.PRESS.add("Run workflow")
page(workflow.render)
ok("workflow re-run", p.structure is not None and len(p.structure.names) == 6)
for mode in ("South - North", "Between two wells", "Custom"):
    fs.OVERRIDES["sec_mode"] = mode
    ok(f"section mode {mode}", page(workflow.render) and not errors(), errors())
fs.OVERRIDES.pop("sec_mode")
# error path: unknown reference
bad = [dict(type="isochore", horizon="X", ref="Nope", direction="below", mode="constant", thickness=10, gx=0, gy=0, role="conformable")]
from core.workflow import run_workflow, WorkflowError
try:
    run_workflow(bad, p.surfaces, p.faults, p.tops, p.lattice)
    ok("workflow error message", False)
except WorkflowError as e:
    ok("workflow error message", "before it is defined" in str(e), str(e))

# zones / grid / export
p.zones = []
fs.PRESS.add("One zone per horizon interval")
ok("zones auto-create", page(zones.render) and len(p.zones) == 5, [z.style for z in p.zones])
ok("zones table renders", page(zones.render) and not errors(), errors())
fs.PRESS.add("Build 3D grid")
fs.OVERRIDES["g_dx"] = 250.0
fs.OVERRIDES["g_dy"] = 250.0
ok("grid builds from UI", page(grid.render) and p.grid is not None and not errors(), errors())
ok("grid QC renders", page(grid.render) and not errors(), errors())
g_filter = p.grid
act_before = g_filter.actnum.copy()
scalar_layers = np.broadcast_to(np.arange(1, g_filter.nk + 1)[:, None, None], g_filter.actnum.shape)
all_mask = S.grid_view_layers(g_filter, "test_view")
full_faces = g_filter.exterior_faces(scalar=scalar_layers)
all_faces = g_filter.exterior_faces(scalar=scalar_layers, layer_mask=all_mask)
ok("default view filter preserves every exterior face", all(np.array_equal(a, b) for a, b in zip(full_faces, all_faces)))
fs.OVERRIDES["test_view_filter"] = "Zones"
fs.OVERRIDES["test_view_zones"] = [1, 3]
zone_mask = S.grid_view_layers(g_filter, "test_view")
ok("zone view filter selects exactly the zone layers", np.array_equal(zone_mask, np.isin(g_filter.layer_zone, [1, 3])))
fs.OVERRIDES["test_view_filter"] = "Layers"
fs.OVERRIDES["test_view_layers"] = (2, 4)
layer_mask = S.grid_view_layers(g_filter, "test_view")
ok("layer view range is global, 1-based and inclusive", np.array_equal(np.flatnonzero(layer_mask), [1, 2, 3]))
_, _, shown_layers = g_filter.exterior_faces(scalar=scalar_layers, layer_mask=layer_mask)
ok("filtered geometry contains only requested layers", set(np.unique(shown_layers)) == {2, 3, 4})
fs.OVERRIDES["test_view_filter"] = "Zones and layers"
both_mask = S.grid_view_layers(g_filter, "test_view")
ok("combined view filters intersect zones and layers", np.array_equal(both_mask, zone_mask & layer_mask))
gap_mask = np.zeros(g_filter.nk, bool)
gap_mask[[1, 3]] = True
_, _, gap_layers = g_filter.exterior_faces(1, 1, scalar_layers, layer_mask=gap_mask)
ok("non-contiguous layer filters combine with I/J cut-away", set(np.unique(gap_layers)) == {2, 4})
empty_mask = np.zeros(g_filter.nk, bool)
ok("empty filter emits no grid faces", all(len(a) == 0 for a in g_filter.exterior_faces(layer_mask=empty_mask)))
fs.OVERRIDES["test_view_filter"] = "Zones"
fs.OVERRIDES["test_view_zones"] = []
fs.MESSAGES.clear()
ok("empty zone selection warns instead of resetting to all layers", not S.grid_view_layers(g_filter, "test_view").any()
   and any(level == "warning" and "No grid layers" in msg for level, msg in fs.MESSAGES))
for prefix in ("v3", "g3"):
    fs.OVERRIDES[prefix + "_filter"] = "Layers"
    fs.OVERRIDES[prefix + "_layers"] = (2, 4)
    ok(f"{prefix} filtered viewer renders", page(viewer.render if prefix == "v3" else grid.render) and not errors(), errors())
    fs.OVERRIDES.pop(prefix + "_filter")
    fs.OVERRIDES.pop(prefix + "_layers")
ok("display filtering leaves ACTNUM unchanged", np.array_equal(act_before, g_filter.actnum))
from core.cpgrid import CPGrid, ZoneSpec
tiny_zc = np.broadcast_to((1000 + 10 * (np.arange(3)[:, None] + np.arange(2)))[..., None, None, None, None],
                          (3, 2, 1, 2, 1, 2)).copy()
tiny_grid = CPGrid(1, 1, 3, np.array([0, 10]), np.array([0, 10]), tiny_zc, np.ones((3, 1, 1), int),
                   np.array([0, 0, 1]), [ZoneSpec("A", "Top", "Mid"), ZoneSpec("B", "Mid", "Base")],
                   np.ones((1, 1), int), [])
tiny_mask = np.array([False, True, False])
vertices, triangles, _ = tiny_grid.exterior_faces(layer_mask=tiny_mask)
ok("isolated interior layer exposes all six faces", len(vertices) == 24 and len(triangles) == 12
   and set(np.unique(vertices[:, 2])) == {1010, 1020})
tiny_grid.actnum[1] = 0
ok("layer filtering never reactivates inactive cells", len(tiny_grid.exterior_faces(layer_mask=tiny_mask)[0]) == 0)
try:
    tiny_grid.exterior_faces(layer_mask=np.ones(2, bool))
    ok("invalid visibility mask is rejected", False)
except ValueError as e:
    ok("invalid visibility mask is rejected", "Layer visibility mask" in str(e))
for key in ("test_view_filter", "test_view_zones", "test_view_layers"):
    fs.OVERRIDES.pop(key)
for prop in ("Zone", "Layer (k)", "Fault block", "Depth", "Thickness", "PORO", "PERMX", "NTG"):
    fs.OVERRIDES["g3_prop"] = prop
    ok(f"grid 3D colour by {prop}", page(grid.render) and not errors(), errors())
fs.OVERRIDES["gs_axis"] = "Column (S-N)"
ok("grid section column", page(grid.render) and not errors(), errors())
fs.OVERRIDES.clear()
fs.PRESS.update(["prep_grdecl", "prep_vtk", "prep_surf"])
ok("export page", page(export.render) and not errors(), errors())
ok("export prepares + offers downloads", {d[1] for d in fs.DOWNLOADS} >= {"MODEL.GRDECL", "model.vtk"}, sorted({d[1] for d in fs.DOWNLOADS}))


# ================================================================ v2: polygons, filters, wells, 3D window, object tree
import numpy as np
from core import polygons as pg_, filters as flt_, wells as wl_

for name, fn in [("polygons", polygons.render), ("wells", wells.render), ("3D window", viewer.render)]:
    ok(f"{name} page renders (demo)", page(fn) and not errors(), errors())

# -- polygon editor round trip
bx, by = p.lattice.xori, p.lattice.yori
fs.COMPONENT_VALUES["geomodel_map_editor"] = dict(kind="polygons", nonce=31, boundary="Licence", polygons=[
    dict(name="Licence", pts=[[bx + 500, by + 500], [bx + 6500, by + 700], [bx + 7000, by + 5000], [bx + 800, by + 5200]]),
    dict(name="Hole", pts=[[bx + 3000, by + 2000], [bx + 4000, by + 2000], [bx + 4000, by + 3000]])])
ok("polygon editor value applied", page(polygons.render) and set(p.polygons) == {"Licence", "Hole"} and p.boundary == "Licence", list(p.polygons))
fs.COMPONENT_VALUES.pop("geomodel_map_editor")
ok("grid invalidated by new boundary", p.grid is None and p.structure is None)

# -- polygon import (XY text) and export
xy = b"> Imported\n%f %f\n%f %f\n%f %f\n" % (bx + 100, by + 100, bx + 3000, by + 100, bx + 1500, by + 2500)
fs.OVERRIDES["poly_up"] = [F("imp.xy", xy)]
fs.PRESS.add("poly_add_imp.xy")
ok("polygon import from XY text", page(polygons.render) and "Imported" in p.polygons, list(p.polygons))
fs.OVERRIDES.pop("poly_up")
fs.DOWNLOADS.clear()
page(polygons.render)
ok("polygon export offered", any(d[1] == "polygons.xy" for d in fs.DOWNLOADS))

# -- clip surfaces to a polygon from the polygon library
fs.OVERRIDES["poly_sel"] = "Licence"
fs.OVERRIDES["poly_tg"] = ["Top_Reservoir"]
fs.PRESS.add("poly_clip")
ok("clip to polygon (library)", page(polygons.render) and not errors(), errors())
zc = p.surfaces["Top_Reservoir"].z
inside_ = pg_.mask(p.lattice, p.polygons["Licence"])
ok("surface clipped: nothing outside the polygon survives", np.isnan(zc[~inside_]).all() and np.isfinite(zc[inside_]).mean() > 0.9,
   f"{np.isfinite(zc).mean():.2f} defined")
ok("raw map untouched", np.isfinite(p.raw["Top_Reservoir"]).all())
fs.OVERRIDES.pop("poly_sel"); fs.OVERRIDES.pop("poly_tg")

# -- filter UI: add a range filter, edit it, undo
fs.OVERRIDES["flt_sel"] = "BCU"
fs.OVERRIDES["flt_newkind"] = "range"
fs.PRESS.add("flt_add")
ok("filter tab: open new-range form", page(surfaces.render) and "tmp_fedit" in fs.session_state, errors())
ed = fs.session_state["tmp_fedit"]
pre = f"fe_BCU_{ed['idx']}_{ed['ver']}_"
fs.OVERRIDES[pre + "lo"] = 1800.0
fs.OVERRIDES[pre + "hi"] = 1900.0
fs.OVERRIDES[pre + "ulo"] = True
fs.OVERRIDES[pre + "uhi"] = True
fs.PRESS.add(pre + "apply")
n_before = int(np.isfinite(p.surfaces["BCU"].z).sum())
ok("filter tab: apply range filter", page(surfaces.render) and len(p.filters["BCU"]["ops"]) == 1 and "tmp_fedit" not in fs.session_state, errors())
zb = p.surfaces["BCU"].z
ok("range filter removed nodes outside 1800-1900", int(np.isfinite(zb).sum()) < n_before and np.nanmin(zb) >= 1800 and np.nanmax(zb) <= 1900,
   f"{np.nanmin(zb):.0f}..{np.nanmax(zb):.0f}")
fs.PRESS.add("undo_BCU")
ok("filter tab: undo button restores the surface", page(surfaces.render) and len(p.filters["BCU"]["ops"]) == 0 and int(np.isfinite(p.surfaces["BCU"].z).sum()) == n_before)
fs.PRESS.add("redo_BCU")
ok("filter tab: redo button", page(surfaces.render) and len(p.filters["BCU"]["ops"]) == 1)
fs.PRESS.add("edit_BCU_0")
page(surfaces.render)
ed = fs.session_state["tmp_fedit"]
pre = f"fe_BCU_{ed['idx']}_{ed['ver']}_"
fs.OVERRIDES[pre + "hi"] = 1950.0
fs.PRESS.add(pre + "apply")
ok("filter tab: edit an existing filter", page(surfaces.render) and p.filters["BCU"]["ops"][0]["max"] == 1950.0, p.filters["BCU"]["ops"])
for k_ in list(fs.OVERRIDES):
    if k_.startswith("fe_"):
        fs.OVERRIDES.pop(k_)
fs.PRESS.add("en_BCU_0")
fs.OVERRIDES["en_BCU_0"] = False
ok("filter tab: switching a filter off", page(surfaces.render) and p.filters["BCU"]["ops"][0]["enabled"] is False and int(np.isfinite(p.surfaces["BCU"].z).sum()) == n_before)
fs.OVERRIDES.pop("en_BCU_0")
fs.PRESS.add("sg_spk_BCU")
ok("smart suggestion adds spike + fill", page(surfaces.render) and [o["type"] for o in p.filters["BCU"]["ops"]][-2:] == ["spikes", "fill"], p.filters["BCU"]["ops"])
fs.OVERRIDES["flt_pname"] = "My preset"
fs.PRESS.add("flt_psave")
ok("save preset", page(surfaces.render) and "My preset" in p.filter_presets)
fs.OVERRIDES.pop("flt_pname")
fs.PRESS.add("reset_BCU")
ok("reset removes all filters (undoable)", page(surfaces.render) and p.filters["BCU"]["ops"] == [] and len(p.filters["BCU"]["undo"]) > 0)
fs.OVERRIDES.pop("flt_sel"); fs.OVERRIDES.pop("flt_newkind")
for v_ in ("Kept / removed", "Filtered map", "Histogram"):
    fs.OVERRIDES["flt_view"] = v_
    ok(f"filter preview: {v_}", page(surfaces.render) and not errors(), errors())
fs.OVERRIDES.pop("flt_view")

# -- wells
p.tops = d.tops.copy()
fs.OVERRIDES["wl_up"] = [F("heads.csv", b"Well,X,Y,KB,TD\nN-1,452500,6702500,20,2200\nN-2,453500,6703500,20,2300\n")]
fs.PRESS.add("wl_merge_heads.csv")
ok("well head import", page(wells.render) and {"N-1", "N-2"} <= set(p.wells), list(p.wells))
fs.OVERRIDES["wl_up"] = [F("svy.csv", b"Well MD INCL AZIM\nN-1 0 0 0\nN-1 800 0 0\nN-1 1600 40 120\nN-1 2200 45 125\n")]
fs.PRESS.add("wl_merge_svy.csv")
ok("deviation survey import", page(wells.render) and p.wells["N-1"].kind.startswith("deviated"), p.wells["N-1"].kind)
fs.OVERRIDES.pop("wl_up")
fs.OVERRIDES["wl_name_"] = "GEN-1"
fs.OVERRIDES["wl_kind_"] = "Deviated - build / hold (generator)"
fs.PRESS.add("wl_save_")
ok("create deviated well with the build/hold generator", page(wells.render) and "GEN-1" in p.wells and len(p.wells["GEN-1"].survey) == 4, errors())
tr_ = wl_.trajectory(p.wells["GEN-1"])
ok("generated well deviates to the east", tr_[-1, 0] - tr_[0, 0] > 300 and abs(tr_[-1, 1] - tr_[0, 1]) < 5, str(tr_[-1].round(0)))
fs.OVERRIDES.pop("wl_name_"); fs.OVERRIDES.pop("wl_kind_")
p.wells.pop("W-2", None)
fs.PRESS.add("wl_fromtops")
ok("wells from tops recreates missing wells", page(wells.render) and "W-2" in p.wells and p.wells["W-2"].kind == "vertical", str(sorted(p.wells)) + str(errors()))

# -- 3D window content
mark_ = len(fs.CALLS)
ok("3D window with grid", page(viewer.render) and not errors(), errors())
comp = [pl for kd, pl in fs.CALLS[mark_:] if kd == "component:geomodel_viewer3d"]
types_ = {o["type"] for o in comp[-1]["scene"]["objects"]} if comp else set()
ok("3D scene has meshes, lines, wells", {"mesh", "lines", "well"} <= types_, types_)
groups_ = {o["group"] for o in comp[-1]["scene"]["objects"]} if comp else set()
ok("3D scene groups", {"Surfaces", "Faults", "Polygons", "Wells"} <= groups_, groups_)
fs.PRESS.add("Run workflow")
page(workflow.render)
mark_ = len(fs.CALLS)
ok("3D window after running the structural model", p.structure is not None and page(viewer.render) and not errors(), errors())
comp = [pl for kd, pl in fs.CALLS[mark_:] if kd == "component:geomodel_viewer3d"]
sm_ = [o for o in comp[-1]["scene"]["objects"] if o["group"] == "Structural model"] if comp else []
ok("structural-model horizons are objects in the 3D window", len(sm_) == len(p.structure.names), f"{len(sm_)} horizons")
ok("horizons share one depth legend", len({(o.get("legend") or {}).get("vmin") for o in sm_}) == 1)
fs.OVERRIDES["v3_clip"] = True
fs.OVERRIDES["v3_prop"] = "PORO"
ok("3D window: clip to boundary + PORO colouring", page(viewer.render) and not errors(), errors())
fs.OVERRIDES.pop("v3_clip"); fs.OVERRIDES.pop("v3_prop")

# -- object tree / navigation (app.py)
import runpy
def run_app():
    runpy.run_path(os.path.join(ROOT, "app.py"), run_name="__main__")
ok("app renders the object tree", page(run_app) and not errors(), errors())
fs.PRESS.add("obj_surface_BCU")
ok("tree click opens Surfaces with focus", page(run_app) and fs.session_state["nav"] == "Surfaces" and S.focus("surface") == "BCU", fs.session_state.get("focus"))
fs.session_state.pop("flt_sel_x", None)
fs.PRESS.add("open_polygon")
page(run_app)
ok("tree 'open' button navigates", fs.session_state["nav"] == "Polygons")
fs.PRESS.add("obj_well_W-6")
page(run_app)
page(wells.render)
sel_ = [v for k_, v in fs.session_state.items() if str(k_).startswith("well_sel")]
ok("tree click focuses the well in the Wells page", S.focus("well") == "W-6" and "W-6" in sel_, sel_)
fs.PRESS.add("top_3D window")
page(run_app)
ok("top button opens the 3D window", fs.session_state["nav"] == "3D window")
fs.session_state["nav"] = "Project"

# -- project round trip keeps the new objects
p3 = pj.from_bytes(pj.to_bytes(p))
ok("v2 objects survive save/load", set(p3.polygons) == set(p.polygons) and set(p3.wells) == set(p.wells) and p3.boundary == p.boundary
   and p3.filters["Top_Reservoir"]["ops"] == p.filters["Top_Reservoir"]["ops"]
   and np.allclose(p3.surfaces["Top_Reservoir"].z, p.surfaces["Top_Reservoir"].z, equal_nan=True))

# every rendered component payload must be strict JSON (browsers reject NaN) and have valid plotly traces
bad_json, bad_traces, n_specs = [], [], 0
for kind, payload in fs.CALLS:
    if kind == "component:geomodel_plotly_view":
        n_specs += 1
        try:
            json.dumps(payload["spec"], allow_nan=False)
        except Exception as e:
            bad_json.append(str(e))
        for tr in payload["spec"]["data"]:
            if "type" not in tr:
                bad_traces.append(tr)
    elif kind == "component:geomodel_viewer3d":
        try:
            json.dumps({k: v for k, v in payload.items() if k != "key"}, allow_nan=False)
        except Exception as e:
            bad_json.append(str(e))
    elif kind == "component:geomodel_map_editor":
        try:
            json.dumps({k: v for k, v in payload.items() if k != "key"}, allow_nan=False)
        except Exception as e:
            bad_json.append(str(e))
ok("plot specs are strict JSON", not bad_json and n_specs > 15, f"{n_specs} specs; {bad_json[:2]}")
ok("every trace has a type", not bad_traces)

# project round trip with results
p.structure = None
p2 = pj.from_bytes(pj.to_bytes(p))
ok("project save/load after UI session", set(p2.faults) == set(p.faults) and len(p2.zones) == 5)

# ===================== v3 UI: algorithms, extension, units, CRS =====================
from core import units as un, interp
fs.PRESS.add("Open demo project")
page(home.render)
p = S.proj()
ok("v3: fresh demo", len(p.surfaces) == 4)

# file units on import (feet in, metres project) + kriging with a variogram
asc = io_surfaces.write_esri_ascii(p.surfaces["Top_Reservoir"].resample_to(Geometry(450000, 6700000, 200, 200, 41, 31)))
fs.OVERRIDES["surf_up"] = [F("ft_map.asc", asc)]
fs.OVERRIDES["imp_uxy"] = "ft"
fs.OVERRIDES["imp_uz"] = "ft"
fs.PRESS.add("add_ft_map.asc")
ok("import with file units ft -> m", page(surfaces.render) and "ft_map" in p.surfaces and
   abs(p.surfaces["ft_map"].geom.xinc - 200 * 0.3048) < 1e-6, errors())
ok("depths scaled on import", abs(np.nanmean(p.surfaces["ft_map"].z) - np.nanmean(p.surfaces["Top_Reservoir"].resample_to(Geometry(450000, 6700000, 200, 200, 41, 31)).z) * 0.3048) < 1e-3)
fs.OVERRIDES["imp_zs"] = "elevation (up +)"
fs.OVERRIDES["imp_uxy"] = "m"; fs.OVERRIDES["imp_uz"] = "m"
p.surfaces.pop("ft_map", None)
fs.PRESS.add("add_ft_map.asc")
page(surfaces.render)
ok("elevation (z up) flips sign on import", np.nanmean(p.surfaces["ft_map"].z) < 0)
fs.OVERRIDES.pop("imp_zs")
fs.OVERRIDES["surf_up"] = [F("pts2.xyz", "\n".join(f"{450000 + 100 * i},{6700000 + 100 * j},{2000 - i - j + (i * j) % 7}" for i in range(0, 80, 4) for j in range(0, 60, 4)).encode())]
for meth, extra in [("kriging", {"imp_pts2.xyz_vg": "exponential", "imp_pts2.xyz_dr": 1}), ("local_poly", {}), ("trend_residual", {}),
                    ("moving_average", {}), ("cubic", {}), ("idw", {}), ("nearest", {})]:
    fs.OVERRIDES["imp_pts2.xyz_meth"] = meth
    fs.OVERRIDES.update(extra)
    p.surfaces.pop("pts2", None)
    fs.PRESS.add("grid_pts2.xyz")
    ok(f"UI gridding with {meth}", page(surfaces.render) and "pts2" in p.surfaces and np.isfinite(p.surfaces["pts2"].z).any() and not errors(), errors())
for k_ in [k for k in fs.OVERRIDES if k.startswith("imp_pts2.xyz")]:
    fs.OVERRIDES.pop(k_)
fs.OVERRIDES.pop("surf_up")

# workflow with the new step types and extension options renders and runs
p.steps = [dict(x) for x in p.steps]
p.steps.append(dict(type="proportional", horizon="Mid_UI", top=[x["horizon"] for x in p.steps if "horizon" in x][0],
                    base=[x["horizon"] for x in p.steps if "horizon" in x][3], fraction=0.5, role="conformable", _id=S.new_id()))
p.steps.append(dict(type="clip", horizon="Mid_UI", zmin=1500, zmax=2600, _id=S.new_id()))
for x in p.steps:
    if x["type"] == "surface":
        x.update(fill="gradient", resample="cubic")
p.invalidate()
fs.PRESS.add("Run")
ok("workflow page with proportional / clip / extension steps", page(workflow.render) and not errors(), errors())
ok("run produced a model with the proportional horizon", p.structure is not None and "Mid_UI" in p.structure.names)
for m_ in ("kriging", "trend_residual"):
    for x in p.steps:
        if x["type"] == "calibrate":
            x["method"] = m_
    ok(f"workflow page edit form for calibrate/{m_}", page(workflow.render) and not errors(), errors())

# filter "extend"
from core import filters as flt
p.fstate("Top_Overburden")
p.commit_filter("Top_Overburden", [flt.default_op("range", min=None, max=1900.0), flt.default_op("extend", mode="decay", length=3000.0)])
ok("extend filter in stack renders in the UI", page(surfaces.render) and not errors(), errors())
ok("extend filter result defined", np.isfinite(p.surfaces["Top_Overburden"].z).all())

# CRS panel: set EPSG + convert depth to feet
z_before = p.surfaces["Top_Reservoir"].z.copy()
fs.OVERRIDES["crs_pick"] = "WGS 84 / UTM 31N (32631)"
fs.OVERRIDES["crs_uz"] = "ft"
fs.OVERRIDES["crs_mode"] = "convert"
fs.PRESS.add("Apply CRS and units")
ok("CRS panel: apply EPSG + convert Z to ft", page(home.render) and p.crs["epsg"] == 32631 and p.crs["z_unit"] == "ft" and p.crs["xy_unit"] == "m", errors())
ok("depths converted to ft", np.allclose(p.surfaces["Top_Reservoir"].z, z_before / 0.3048, equal_nan=True))
ok("labels follow the project units", un.z() == "ft" and un.xy() == "m")
ok("pages render with mixed units", all(page(fn) for fn in (surfaces.render, workflow.render, tops.render, wells.render, faults.render, zones.render)) and not errors(), errors())
fs.OVERRIDES["crs_mode"] = "relabel"
fs.OVERRIDES["crs_uz"] = "m"
fs.PRESS.add("Apply CRS and units")
page(home.render)
ok("relabel does not touch the numbers", np.allclose(p.surfaces["Top_Reservoir"].z, z_before / 0.3048, equal_nan=True) and p.crs["z_unit"] == "m")
fs.OVERRIDES["crs_mode"] = "convert"
fs.OVERRIDES["crs_uz"] = "m"
for k_ in ("crs_pick", "crs_uz", "crs_mode"):
    fs.OVERRIDES.pop(k_, None)

# reproject through the panel
p.crs.update(epsg=32631, xy_unit="m", z_unit="m")
fs.OVERRIDES["rp_tgt"] = "WGS 84 / UTM 32N (32632)"
fs.PRESS.add("Reproject project")
w0 = {n: (w.x, w.y) for n, w in p.wells.items()}
ok("reproject via the UI", page(home.render) and p.crs["epsg"] == 32632 and not errors(), errors())
n0 = next(iter(w0))
ok("well moved by the expected transform", abs(un.transform_xy(*w0[n0], 32631, 32632)[0] - p.wells[n0].x) < 1e-6)
fs.OVERRIDES.pop("rp_tgt")
ok("steps survive: workflow still runs after reprojection", page(workflow.render) and not errors(), errors())

# export page with unit options
p.invalidate()
fs.PRESS.add("Run")
page(workflow.render)
fs.PRESS.add("Build grid")
page(grid.render)
fs.OVERRIDES["ex_sys"] = "FIELD"
fs.OVERRIDES["ex_z"] = "ft"
fs.OVERRIDES["ex_xy"] = "ft"
fs.PRESS.update(["Prepare GRDECL", "Prepare surfaces ZIP"])
fs.DOWNLOADS.clear()
ok("export page with FIELD units", page(export.render) and not errors(), errors())
ok("FIELD GRDECL offered", any("GRDECL" in d[0] for d in fs.DOWNLOADS) or p.grid is None, [d[0] for d in fs.DOWNLOADS][:4])
for k_ in ("ex_sys", "ex_z", "ex_xy"):
    fs.OVERRIDES.pop(k_)

# ===================== v3.1 UI: layers step, fences, curtain =====================
from core import fence as fcn
from core.polygons import Polygon as _Poly
fs.PRESS.add("Open demo project")
page(home.render)
p = S.proj()
hs_ = [x["horizon"] for x in p.steps if x["type"] in ("surface", "isochore")]
p.steps.append(dict(type="layers", top=hs_[2], base=hs_[4], style="proportional", n=4, prefix="Lay", role="conformable", _id=S.new_id()))
p.steps.append(dict(type="layers", top=hs_[2], base=hs_[4], style="follow_top", dz=40.0, prefix="Dz", role="conformable", _id=S.new_id()))
p.steps.append(dict(type="layers", top=hs_[2], base=hs_[4], style="fractions", fractions=[0.3, 0.6], prefix="Fr", role="conformable", _id=S.new_id()))
p.invalidate()
fs.PRESS.add("Run workflow")
ok("workflow page with 3 layers steps runs", page(workflow.render) and not errors() and p.structure is not None, errors())
ok("layer horizons present in the model", sum(n.startswith(("Lay_", "Dz_", "Fr_")) for n in p.structure.names) >= 3 + 3 + 2)
from views.workflow import _layer_horizon_set
ok("layer horizons are listed as layer-generated", {"Lay_1", "Lay_2", "Lay_3", "Fr_1"} <= _layer_horizon_set(p))
# a later step can reference a layer horizon
p.steps.append(dict(type="smooth", horizon="Lay_2", sigma=1.0, _id=S.new_id()))
p.invalidate()
fs.PRESS.add("Run workflow")
ok("a step can use a layer horizon", page(workflow.render) and not errors() and p.structure is not None, errors())

# fences: editor value -> project
b_ = p.lattice.bounds()
fence_pts = [[b_[0] + 600, b_[2] + 500], [b_[0] + 3000, b_[2] + 3000], [b_[1] - 800, b_[3] - 900]]
orig_call = fs.declare_component
fs.OVERRIDES["component:geomodel_map_editor"] = None
fence_val = dict(kind="fences", nonce=991, polygons=[dict(name="FenceA", pts=fence_pts), dict(name="Tiny", pts=[[0, 0]])])
import views.workflow as _wv
_wv.map_editor = lambda *a, **k: fence_val if a and a[0] == "fences" else None
ok("fence editor value stored on the project (1-vertex fence dropped)", page(workflow.render) and list(p.fences) == ["FenceA"], list(p.fences))
ok("fence points kept", np.allclose(p.fences["FenceA"].pts, fence_pts))
fence_val["nonce"] = 992
fence_val["polygons"].append(dict(name="FenceA", pts=fence_pts[:2]))
page(workflow.render)
ok("duplicate fence names are made unique", sorted(p.fences) == ["FenceA", "FenceA_2"], sorted(p.fences))
_wv.map_editor = lambda *a, **k: None
for mode in ("Drawn fence", "Through wells", "West - East", "South - North", "Custom"):
    fs.OVERRIDES["sec_mode"] = mode
    fs.DOWNLOADS.clear()
    ok(f"cross-section tab: {mode}", page(workflow.render) and not errors(), errors())
fs.OVERRIDES.pop("sec_mode")
fs.OVERRIDES["sec_mode"] = "Drawn fence"
mark = len(fs.CALLS)
page(workflow.render)
secs = [c for c in fs.CALLS[mark:] if c[0] == "component:geomodel_plotly_view" and any("Distance along section" in str(tr) for tr in [c[1]["spec"]["layout"]])]
ok("section plot spec has fault-crossing markers + vertex ticks", bool(secs) and len(secs[-1][1]["spec"]["layout"]["shapes"]) >= 2, len(secs))
fs.OVERRIDES.pop("sec_mode")

# curtain in the 3D tab
fs.OVERRIDES["r3_fen"] = ["FenceA"]
mark = len(fs.CALLS)
ok("3D tab with a fence curtain renders", page(workflow.render) and not errors(), errors())
v3 = [c for c in fs.CALLS[mark:] if c[0] == "component:geomodel_viewer3d"]
objs = v3[-1][1]["scene"]["objects"] if v3 else []
ok("curtain objects reach the viewer", any(o["name"] == "Fence FenceA" for o in objs) and any(o["name"] == "Fence FenceA horizons" for o in objs), [o["name"] for o in objs][:12])
ok("scene with curtain is strict JSON", bool(v3) and json.dumps({k: v for k, v in v3[-1][1].items() if k != "key"}, allow_nan=False) is not None)
ok("layer horizons are off by default in 3D", not any(o["name"].startswith(("Lay_", "Dz_", "Fr_")) for o in objs))
fs.OVERRIDES.pop("r3_fen")
p2 = pj.from_bytes(pj.to_bytes(p))
ok("fences + layer steps survive save/load", set(p2.fences) == set(p.fences) and any(s["type"] == "layers" for s in p2.steps))


# ===================== v3.2 UI: fault types, zone steps, grid control, properties =====================
from views import properties as vprops
from core import props as pp
fs.OVERRIDES.clear()
fs.PRESS.clear()
fs.PRESS.add("Open demo project")
page(home.render)
p = S.proj()

# faults page with the new types
fs.COMPONENT_VALUES["geomodel_map_editor"] = dict(kind="faults", nonce=71, faults=[
    dict(name="FS", trace=[[452000, 6701000], [455000, 6704500]], ftype="strike_slip", throw=0, dip=85, hw_side="left", profile="plateau", drag=200, growth=0,
         zref=2050, slip=120.0, slip_sense="sinistral", pivot=0.5, heave=0.0, color="#D7263D"),
    dict(name="FT", trace=[[453000, 6700500], [455500, 6702500]], ftype="transverse", throw=40, dip=70, hw_side="left", profile="elliptical", drag=250,
         growth=0, zref=2050, slip=0.0, slip_sense="dextral", pivot=0.3, heave=0.5, color="#2E294E")])
ok("fault editor accepts strike-slip + transverse with their parameters",
   page(faults.render) and p.faults["FS"].slip == 120.0 and p.faults["FS"].slip_sense == "sinistral" and p.faults["FT"].pivot == 0.3 and p.faults["FT"].heave == 0.5 and not errors(), errors())
fs.COMPONENT_VALUES.pop("geomodel_map_editor")
ok("faults page renders new fault table", page(faults.render) and not errors(), errors())
fs.PRESS.add("Run workflow")
S.sync_fault_step(p)
p.invalidate()
ok("workflow with new fault types runs", page(workflow.render) and p.structure is not None and not errors(), errors())
p = pj.from_bytes(pj.to_bytes(p))
S.set_proj(p) if hasattr(S, "set_proj") else None
fs.PRESS.add("Open demo project")
page(home.render)
p = S.proj()

# zone steps through the UI helpers
p.steps = [s for s in p.steps if s["type"] in ("faults", "surface")]
p.steps += [dict(type="zone", name="Res_Upper", top="Top_Reservoir", horizon="Mid_Reservoir", mode="constant", thickness=60.0, tmin=40.0, nlayers=6, role="conformable", _id=S.new_id()),
            dict(type="zone", name="Res_Lower", top="Mid_Reservoir", horizon="Base_Reservoir", mode="map", surface="Isochore_Res", smooth=2.0, calibrate=True,
                 label="Base_Reservoir", method="min_curvature", radius=3500.0, nlayers=8, role="conformable", _id=S.new_id())]
p.invalidate()
fs.PRESS.add("Run workflow")
ok("workflow page renders zone steps and runs", page(workflow.render) and p.structure is not None and not errors() and len(p.structure.zone_defs) == 2, errors())
fs.OVERRIDES["new_kind"] = "zone"
ok("zone step form renders (add-step)", page(workflow.render) and not errors(), errors())
fs.OVERRIDES.pop("new_kind")
fs.PRESS.add("Create / update grid zones")
ok("Zones tab: create grid zones from zone steps", page(workflow.render) and [z.name for z in p.zones] == ["Res_Upper", "Res_Lower"] and p.zones[1].nlayers == 8, [z.name for z in p.zones])

# grid page: count mode + rotation + refinement
fs.OVERRIDES["gc_mode"] = "count"
fs.OVERRIDES["gc_ni"] = 30
fs.OVERRIDES["gc_nj"] = 20
fs.OVERRIDES["gc_ang"] = 20.0
fs.PRESS.add("Build 3D grid")
ok("grid page: count mode + rotation builds", page(grid.render) and p.grid is not None and p.grid.rotated and abs(p.grid.ni - 30) <= 1 and not errors(), errors())
ok("grid params persisted (mode, angle)", p.grid_params["mode"] == "count" and p.grid_params["angle"] == 20.0)
ok("rotated grid page re-renders (3D, sections, QC)", page(grid.render) and not errors(), errors())
fs.OVERRIDES.update({"gc_mode": "size", "gc_ang": 0.0, "g_dx": 400.0, "g_dy": 400.0})
fs.PRESS.add("Add windows around the fault traces")
ok("fault refinement windows added", page(grid.render) and len(fs.CALLS) > 0 and not errors(), errors())
fs.PRESS.add("Build 3D grid")
ok("grid with refinement windows builds", page(grid.render) and p.grid is not None and not errors(), errors())
ok("refinement made the spacing non-uniform", len(set(np.round(np.diff(p.grid.xs), 3))) > 1 or len(set(np.round(np.diff(p.grid.ys), 3))) > 1, p.grid.notes)
fs.OVERRIDES.clear()

# properties page
ok("properties page renders with a grid", page(vprops.render) and not errors(), errors())
fs.PRESS.add("Populate PORO")
ok("populate from zones", page(vprops.render) and set(p.properties) >= set(pp.ZONE_PROPS), list(p.properties))
fs.OVERRIDES["pr_code"] = "PORO_T = by_zone(0.1, 0.2) + 0.01 * gauss(3)\nPERMT = 10 ** (12 * PORO_T - 1.5)"
fs.PRESS.add("Run and store")
ok("calculator stores two properties", page(vprops.render) and {"PORO_T", "PERMT"} <= set(p.properties) and not errors(), errors())
fs.OVERRIDES["pr_code"] = "import os"
fs.PRESS.add("Run and store")
ok("unsafe script reports an error and stores nothing", page(vprops.render) and any("not allowed" in e for e in errors()) and "os" not in p.properties, errors())
fs.OVERRIDES["pr_code"] = "FAC = where(DEPTH < 2100, 1, 2)"
fs.OVERRIDES["pr_rkind"] = "discrete"
fs.PRESS.add("Run and store")
ok("discrete property via calculator", page(vprops.render) and p.properties.get("FAC") is not None and p.properties["FAC"].kind == "discrete", errors())
fs.OVERRIDES.clear()
for prop in ("PORO_T", "FAC", "PERMT"):
    fs.OVERRIDES["pv_prop"] = prop
    mark = len(fs.CALLS)
    ok(f"properties view for {prop}", page(vprops.render) and not errors(), errors())
v3p = [c for c in fs.CALLS[mark:] if c[0] == "component:geomodel_viewer3d"]
ok("3D viewer receives a property-coloured grid", bool(v3p) and any(o["name"] == "3D grid" for o in v3p[-1][1]["scene"]["objects"]))
fs.OVERRIDES.clear()
fs.OVERRIDES["g3_prop"] = "PORO_T"
ok("grid page colours by a user property", page(grid.render) and not errors(), errors())
fs.OVERRIDES.clear()
ok("object tree lists properties", any(k["kind"] == "prop" and len(k["items"]) >= 5 for g_ in __import__("core.objects", fromlist=["tree"]).tree(p) for k in g_["kinds"]))
fs.PRESS.update(["prep_grdecl"])
fs.OVERRIDES["ex_props"] = ["PORO", "PORO_T", "FAC"]
fs.DOWNLOADS.clear()
ok("export page with user properties", page(export.render) and not errors(), errors())
ok("GRDECL download prepared with user props", any(d[1] == "MODEL.GRDECL" for d in fs.DOWNLOADS), fs.DOWNLOADS[:2] if fs.DOWNLOADS else "")
fs.OVERRIDES.clear()
p2 = pj.from_bytes(pj.to_bytes(p))
ok("properties + zone steps survive save/load", set(p2.properties) == set(p.properties) and any(s["type"] == "zone" for s in p2.steps))
# rebuilding with other dims drops mismatching properties
fs.OVERRIDES.update({"g_dx": 700.0, "g_dy": 700.0})
fs.PRESS.add("Build 3D grid")
page(grid.render)
ok("rebuild with new dimensions removes mismatching properties", all(v.values.shape == (p.grid.nk, p.grid.nj, p.grid.ni) for v in p.properties.values()))
fs.OVERRIDES.clear()


fs.OVERRIDES.clear()
fs.PRESS.add("Generate")
ok("Properties page: generate geometric properties", page(vprops.render) and {"DEPTH", "ZONE", "K", "ZFRAC", "VOLUME", "DZ"} <= set(p.properties) and not errors(), errors())
fs.OVERRIDES["pv_prop"] = "ZONE"
ok("view a geometric discrete property", page(vprops.render) and not errors(), errors())
fs.OVERRIDES.clear()

# ===================== v3.2: stochastic modelling tab =====================
fs.OVERRIDES.clear()
fs.PRESS.clear()
for k_ in ("sx_last",):
    fs.st_state = None
p.stochastic = {}
ok("Stochastic tab renders with default config", page(vprops.render) and not errors() and set(p.stochastic["props"]) == {"PORO", "PERM", "NTG"}, errors())
fs.OVERRIDES["sx_nreal"] = 2
fs.OVERRIDES["sx_cphi"] = 0.1
fs.PRESS.add("Run stochastic workflow")
ok("run stochastic workflow stores properties (2 realisations)", page(vprops.render) and {"PORO_R1", "PORO_R2", "PERMX_R1", "NTG_R2", "NET_R1"} <= set(p.properties) and not errors(), errors())
ok("stochastic properties flagged with their source", p.properties["PORO_R1"].source == "stochastic" and p.properties["NET_R1"].kind == "discrete")
ok("QC (histogram, cross-plot, variogram, correlation) renders", page(vprops.render) and not errors(), errors())
ok("settings persisted on the project", p.stochastic["nreal"] == 2 and abs(p.stochastic["cut"]["phi"] - 0.1) < 1e-9)
fs.OVERRIDES["sx_nreal"] = 1
fs.OVERRIDES["sx_pm"] = "transform"
fs.PRESS.add("Run stochastic workflow")
ok("permeability-from-porosity mode runs", page(vprops.render) and "PERMX" in p.properties and not errors(), errors())
fs.OVERRIDES["sx_dist_PORO"] = "histogram"
fs.PRESS.add("Run stochastic workflow")
ok("histogram distribution runs", page(vprops.render) and not errors(), errors())
fs.OVERRIDES["sx_dist_PORO"] = "values"
fs.OVERRIDES["sx_vals_PORO"] = "0.1 0.15 0.2 0.25 0.3"
fs.PRESS.add("Run stochastic workflow")
ok("pasted-values distribution runs", page(vprops.render) and not errors(), errors())
fs.OVERRIDES["sx_c1"] = 0.9
fs.OVERRIDES["sx_c2"] = 0.9
fs.OVERRIDES["sx_c3"] = -0.9
fs.OVERRIDES["sx_pm"] = "field"
ok("invalid correlation shows an error and disables nothing silently", page(vprops.render) and any("positive definite" in e for e in errors()), errors())
fs.OVERRIDES.clear()
p2 = pj.from_bytes(pj.to_bytes(p))
ok("stochastic properties + settings survive save/load", "PORO" in p2.properties and p2.stochastic["props"]["PORO"]["dist"] == p.stochastic["props"]["PORO"]["dist"])


# ===================== v3.2: volumetrics + analysis & sections =====================
from views import volumetrics as vvol, analysis as vana
from core.polygons import Polygon
from core import objects as _obj
fs.OVERRIDES.clear()
fs.PRESS.clear()
p.volumetrics = {}
p.properties.update(pp.zone_defaults(p.grid))
ok("volumetrics page renders with defaults", page(vvol.render) and not errors() and "contacts" in p.volumetrics, errors())
owc0 = p.volumetrics["contacts"]["owc"]
fs.OVERRIDES["vo_owc"] = owc0 + 25.0
fs.OVERRIDES["vo_bo"] = 1.4
ok("OWC and Bo edits persist on the project", page(vvol.render) and abs(p.volumetrics["contacts"]["owc"] - (owc0 + 25.0)) < 1e-9 and p.volumetrics["fluid"]["Bo"] == 1.4, errors())
fs.OVERRIDES["vo_usegoc"] = True
ok("gas cap enabled", page(vvol.render) and p.volumetrics["contacts"]["goc"] is not None and not errors(), errors())
fs.OVERRIDES["vo_goc"] = p.volumetrics["contacts"]["owc"] + 50.0
ok("GOC below OWC shows a warning and no crash", page(vvol.render), errors())
fs.OVERRIDES["vo_goc"] = p.volumetrics["contacts"]["owc"] - 30.0
fs.OVERRIDES["vo_disp"] = "field"
ok("field units render", page(vvol.render) and not errors(), errors())
for mode in ("satheight", "constant"):
    fs.OVERRIDES["vo_swm"] = mode
    ok(f"Sw mode {mode} renders", page(vvol.render) and not errors(), errors())
fs.OVERRIDES["vo_swm"] = "property"
ok("Sw from property without SW property degrades gracefully", page(vvol.render) and not any("Traceback" in e for e in errors()), errors())
fs.OVERRIDES["vo_swm"] = "constant"
fs.PRESS.add("Run contact scan")
ok("contact scan runs", page(vvol.render) and not errors(), errors())
ok("contact scan result chart renders", page(vvol.render) and not errors(), errors())
p.volumetrics["unc"]["n"] = 20
fs.OVERRIDES["vo_n"] = 20
fs.PRESS.add("Run tornado")
ok("tornado + Monte-Carlo run", page(vvol.render) and not errors(), errors())
ok("uncertainty results render", page(vvol.render) and not errors(), errors())
fs.PRESS.add("Store as properties")
ok("store volumetric results as properties", page(vvol.render) and {"FLUID", "SW", "VOL_STOIIP", "VOL_HCPV", "VOL_GRV", "VOL_NET"} <= set(p.properties) and not errors(), errors())
ok("stored FLUID is discrete with source volumetrics", p.properties["FLUID"].kind == "discrete" and p.properties["FLUID"].source == "volumetrics")
for n_ in ("PORO", "NTG"):
    p.properties[n_ + "_R2"] = pp.make_property(p.grid, n_ + "_R2", p.properties[n_].values * 0.9, "continuous", "frac")
fs.OVERRIDES["vo_sphi"] = "PORO"
ok("realisation tab offers the computation", page(vvol.render) and not errors(), errors())
fs.PRESS.add("Compute volumetrics for")
ok("volumetrics over realisations", page(vvol.render) and not errors(), errors())
fs.OVERRIDES.clear()
fs.PRESS.clear()
p2 = pj.from_bytes(pj.to_bytes(p))
ok("volumetrics settings round-trip through the project file", p2.volumetrics["contacts"]["owc"] == p.volumetrics["contacts"]["owc"] and p2.volumetrics["display"] == "field")
ok("object tree lists volumetrics and analysis", {"vol", "analysis"} <= {k["kind"] for g_ in _obj.tree(p) for k in g_["kinds"] if k["items"]})

# analysis page
ok("analysis page renders", page(vana.render) and not errors(), errors())
for split in ("zone", "fault block", "layer", "fluid", "none"):
    fs.OVERRIDES["an_ss"] = split
    fs.OVERRIDES["an_hs"] = split
    fs.OVERRIDES["an_cs"] = split
    ok(f"analysis split by {split}", page(vana.render) and not errors(), errors())
fs.OVERRIDES.clear()
fs.OVERRIDES["an_lo1"] = "0.1"
fs.OVERRIDES["an_f1"] = "PORO"
ok("analysis with a value filter", page(vana.render) and not errors(), errors())
fs.OVERRIDES["an_hi1"] = "0.0001"
ok("filter that removes all cells shows a note", page(vana.render) and not errors(), errors())
fs.OVERRIDES.clear()
fs.OVERRIDES["an_lx"] = True
fs.OVERRIDES["an_x"] = "PORO"
fs.OVERRIDES["an_y"] = "PERMX"
ok("crossplot with log axis", page(vana.render) and not errors(), errors())
fs.OVERRIDES.clear()
for md in ("average", "sum", "min", "max", "thickness-weighted"):
    fs.OVERRIDES["an_mm"] = md
    ok(f"map type {md}", page(vana.render) and not errors(), errors())
fs.OVERRIDES.clear()
fs.OVERRIDES["an_pz"] = p.grid.zones[1].name
ok("vertical profile for one zone", page(vana.render) and not errors(), errors())
fs.OVERRIDES.clear()

# property cross-sections
for mode in ("row (J)", "column (I)"):
    fs.OVERRIDES["sc_mode"] = mode
    ok(f"section {mode}", page(vana.render) and not errors(), errors())
fs.OVERRIDES["sc_props"] = ["PORO", "NTG", "FLUID"]
ok("three stacked properties incl. discrete FLUID with contacts", page(vana.render) and not errors(), errors())
fs.OVERRIDES["sc_mode"] = "fence"
p.fences = {"F_test": Polygon("F_test", [[float(p.grid.xs[0] + 150), float(p.grid.ys[0] + 150)], [float(p.grid.xs[-1] - 150), float(p.grid.ys[-1] - 150)]])}
ok("fence section", page(vana.render) and not errors(), errors())
fs.OVERRIDES.clear()
fs.OVERRIDES["sc_mode"] = "fence"
p.fences = {}
ok("fence mode without fences gives guidance, no crash", page(vana.render) and not errors(), errors())
fs.OVERRIDES.clear()
sp_ = [c for c in fs.CALLS if isinstance(c, dict)] if hasattr(fs, "CALLS") else []


# ===================== v3.2: planes & regions, fluid split, new exports =====================
fs.OVERRIDES.clear(); fs.OVERRIDES.update(sx_c1=0.6, sx_c2=0.3, sx_c3=0.2, sx_pm='field')
fs.PRESS.clear()
p.stochastic = {}
for n_ in ("FLUID", "REGION", "SEGMENT", "FAULT_BLOCK", "OWC_DEPTH", "HAOWC", "GOC_DEPTH", "HAGOC"):
    p.properties.pop(n_, None)
ok("Planes & regions tab renders", page(vprops.render) and not errors(), errors())
fs.PRESS.add("Create plane properties")
ok("plane properties stored", page(vprops.render) and {"HAP_PLANE1", "FRAC_PLANE1", "PLANE_REGION"} <= set(p.properties) and not errors(), errors())
ok("plane region has a legend", len(p.properties["PLANE_REGION"].legend) == 2)
fs.PRESS.add("Create contact properties")
ok("contact properties stored (FLUID with legend)", page(vprops.render) and {"OWC_DEPTH", "HAOWC", "FLUID"} <= set(p.properties) and p.properties["FLUID"].legend.get("2") == "oil" and not errors(), errors())
fs.PRESS.add("Create FAULT_BLOCK")
ok("FAULT_BLOCK, REGION and SEGMENT stored", page(vprops.render) and {"FAULT_BLOCK", "REGION", "SEGMENT"} <= set(p.properties) and not errors(), errors())
ok("segment legend names zone / block", all("/ Block" in v for v in p.properties["SEGMENT"].legend.values()))
fs.OVERRIDES["rg_mode"] = "zone x fault block x fluid"
fs.PRESS.add("Create FAULT_BLOCK")
ok("segments with fluid", page(vprops.render) and any(v.endswith(("oil", "water", "gas")) for v in p.properties["SEGMENT"].legend.values()) and not errors(), errors())
fs.OVERRIDES.clear(); fs.OVERRIDES.update(sx_c1=0.6, sx_c2=0.3, sx_c3=0.2, sx_pm='field')
fl_saved = p.properties.pop("FLUID")
for split in ("fluid", "region", "segment"):
    fs.OVERRIDES["an_ss"] = split
    fs.OVERRIDES["an_hs"] = split
    fs.OVERRIDES["an_cs"] = split
    ok(f"analysis split by {split} (FLUID computed from the contacts when not stored)", page(vana.render) and not errors(), errors())
fs.OVERRIDES.clear(); fs.OVERRIDES.update(sx_c1=0.6, sx_c2=0.3, sx_c3=0.2, sx_pm='field')
p.properties["FLUID"] = fl_saved
fs.OVERRIDES["sc_props"] = ["PORO", "FLUID", "SEGMENT"]
ok("section with FLUID and SEGMENT panels", page(vana.render) and not errors(), errors())
fs.OVERRIDES.clear(); fs.OVERRIDES.update(sx_c1=0.6, sx_c2=0.3, sx_c3=0.2, sx_pm='field')
fs.OVERRIDES["ex_ra"] = "FIPNUM"
fs.OVERRIDES["ex_sa"] = "EQLNUM"
fs.PRESS.update(["Prepare GRDECL", "Prepare EGRID", "Prepare INIT", "Prepare package"])
fs.DOWNLOADS.clear()
ok("export page: EGRID, INIT and package prepared", page(export.render) and {"MODEL.EGRID", "MODEL.INIT", "geomodel_export.zip", "MODEL.GRDECL"} <= {d[1] for d in fs.DOWNLOADS} and not errors(),
   (sorted({d[1] for d in fs.DOWNLOADS}), errors()))
fs.OVERRIDES.clear(); fs.OVERRIDES.update(sx_c1=0.6, sx_c2=0.3, sx_c3=0.2, sx_pm='field')
fs.PRESS.clear()
p2 = pj.from_bytes(pj.to_bytes(p))
ok("regions and legends survive save/load", p2.properties["SEGMENT"].legend == p.properties["SEGMENT"].legend)


fs.OVERRIDES.clear(); fs.OVERRIDES.update(sx_c1=0.6, sx_c2=0.3, sx_c3=0.2, sx_pm='field')
fs.PRESS.add("Prepare RESQML")
ok("export page offers RESQML (or explains what is missing)", page(export.render) and not errors(), errors())
fs.OVERRIDES.clear(); fs.PRESS.clear()

from views import faults as vflt
fs.OVERRIDES.clear(); fs.PRESS.clear()
p.fault_mult = {list(p.faults)[0]: 0.1}
ok("faults page: transmissibility + juxtaposition render", page(vflt.render) and not errors(), errors())
fs.OVERRIDES["ex_faults"] = True
fs.PRESS.add("Prepare GRDECL")
fs.DOWNLOADS.clear()
ok("export with FAULTS / MULTFLT", page(export.render) and any(d[1] == "MODEL.GRDECL" for d in fs.DOWNLOADS) and not errors(), errors())

# ===================== v3.3: well logs, blocking, variograms, kriging, conditioning =====================
from core import logs as lgs_, wells as wl_u
p = S.proj()
p.stochastic = {}
p.stochastic = {}
las_files = []
for n_, w_ in p.wells.items():
    md_ = np.arange(0, 3000.0, 0.5)
    xyz_ = lgs_.path_at_md(w_, md_)
    por_ = 0.15 + 0.08 * np.sin(xyz_[:, 2] / 15.0)
    las_files.append(F(f"{n_}.las", lgs_.to_las(n_, dict(md=md_, curves=dict(PHIE=por_), units=dict(PHIE="v/v")))))
las_files.append(F("junk.las", b"not a las file"))
fs.OVERRIDES.clear(); fs.PRESS.clear()
fs.OVERRIDES["las_up"] = las_files
fs.OVERRIDES["sx_c1"] = 0.6; fs.OVERRIDES["sx_c2"] = 0.3; fs.OVERRIDES["sx_c3"] = 0.2; fs.OVERRIDES["sx_pm"] = "field"
ok("well logs tab: LAS import (junk reported, wells stored)", page(vprops.render) and len(p.logs) == len(p.wells) and any("junk.las" in e for e in errors()), errors())
fs.OVERRIDES.pop("las_up")
fs.OVERRIDES["blk_curve"] = "PHIE"
fs.OVERRIDES["blk_name"] = "PHIE_BLK"
fs.PRESS.add("Block wells")
ok("block logs into the grid -> property", page(vprops.render) and "PHIE_BLK" in p.properties and p.properties["PHIE_BLK"].source == "blocked wells"
   and int(np.sum(~np.isnan(p.properties["PHIE_BLK"].values))) > 50 and not errors(), errors())
fs.PRESS.clear()
ok("variogram tab renders for the blocked property", page(vprops.render) and not errors(), errors())
fs.PRESS.add("Apply fitted ranges to every zone's stochastic setup")
ok("apply fitted ranges updates the stochastic table", page(vprops.render) and p.stochastic["props"]["PORO"]["rows"][0]["vtype"] == "spherical" and not errors(), errors())
fs.PRESS.clear()
fs.OVERRIDES["kr_out"] = "PHIE_KRG"
fs.PRESS.add("Krige")
ok("kriging stores a property without gaps", page(vprops.render) and "PHIE_KRG" in p.properties and not np.isnan(p.properties["PHIE_KRG"].values[p.grid.actnum > 0]).any() and not errors(), errors())
fs.PRESS.clear()
fs.OVERRIDES["sx_cond_PORO"] = "PHIE_BLK"
fs.PRESS.add("Run stochastic workflow")
ok("stochastic run conditioned to blocked wells", page(vprops.render) and p.stochastic["cond"].get("PORO") == "PHIE_BLK" and not errors(), errors())
bm_ = ~np.isnan(p.properties["PHIE_BLK"].values)
ok("conditioned PORO equals the blocked data in their cells", np.abs(p.properties["PORO"].values[bm_] - p.properties["PHIE_BLK"].values[bm_]).max() < 1e-5)
fs.PRESS.clear(); fs.OVERRIDES.clear()
p3_ = pj.from_bytes(pj.to_bytes(p))
ok("logs + blocked properties + conditioning setup survive save/load", set(p3_.logs) == set(p.logs) and "PHIE_BLK" in p3_.properties and p3_.stochastic["cond"]["PORO"] == "PHIE_BLK")


# ===================== v3.3: upscaling page =====================
from views import upscaling as vup
p = S.proj()
fs.OVERRIDES.clear(); fs.PRESS.clear(); fs.MESSAGES.clear()
p.properties.update(pp.zone_defaults(p.grid))
ok("upscaling page renders before running", page(vup.render) and not errors(), errors())
fs.OVERRIDES["up_ci"] = 3
fs.OVERRIDES["up_cj"] = 3
fs.OVERRIDES["up_meth"] = "geometric"
fs.PRESS.add("Build coarse grid and upscale")
ok("upscale run (geometric) stores a coarse result", page(vup.render) and "up_result" in fs.session_state and not errors(), errors())
fs.PRESS.clear()
rr_ = fs.session_state["up_result"]
ok("coarse grid is smaller and volumes agree", rr_["c"].grid.ncells < p.grid.ncells and abs(rr_["qc"]["bulk_coarse"] / rr_["qc"]["bulk_fine"] - 1) < 0.03, (rr_["c"].grid.ncells, p.grid.ncells, rr_["qc"]["bulk_coarse"] / rr_["qc"]["bulk_fine"]))
fs.DOWNLOADS.clear()
for lab_ in ("Prepare coarse GRDECL", "Prepare coarse EGRID", "Prepare coarse INIT"):
    fs.PRESS.add(lab_)
ok("result page renders + coarse GRDECL / EGRID / INIT downloads", page(vup.render) and {d[1] for d in fs.DOWNLOADS} >= {"COARSE.GRDECL", "COARSE.EGRID", "COARSE.INIT"} and not errors(), (errors(), fs.DOWNLOADS))
fs.PRESS.clear()
fs.OVERRIDES["up_meth"] = "flow"
fs.OVERRIDES["up_ci"] = 4
fs.OVERRIDES["up_cj"] = 4
fs.PRESS.add("Build coarse grid and upscale")
ok("flow-based upscaling runs from the page", page(vup.render) and any("flow" in v["method"] for v in fs.session_state["up_result"]["res"].values()) and not errors(), errors())
ok("upscale settings stored on the project", p.upscale["ci"] == 4 and p.upscale["method"] == "flow")
from core import objects as _o2
ok("object tree lists Upscaling", any(i["name"] == "Upscaling" for g_ in _o2.tree(p) for k_ in g_["kinds"] for i in k_["items"]))
fs.OVERRIDES.clear(); fs.PRESS.clear()


# ===================== v3.3: inclined pillars from the 3D grid page =====================
p = S.proj()
fs.OVERRIDES.clear(); fs.PRESS.clear(); fs.MESSAGES.clear()
ok("3D grid page renders with the tilt controls", page(grid.render) and not errors(), errors())
fs.OVERRIDES["gc_tilt"] = True
fs.OVERRIDES["gc_trad"] = 3.0
fs.PRESS.add("Build 3D grid")
okb_ = page(grid.render)
ok("grid builds with inclined pillars from the page", okb_ and p.grid is not None and p.grid.tilted and p.grid_params.get("tilt") is True and not errors(), (errors(), [n for n in (p.grid.notes if p.grid else [])]))
fs.PRESS.clear()
ok("grid page + 3D window render on the tilted grid", page(grid.render) and page(viewer.render) and not errors(), errors())
fs.OVERRIDES["gc_tilt"] = False
fs.PRESS.add("Build 3D grid")
ok("switching tilt off rebuilds vertical pillars", page(grid.render) and p.grid is not None and not p.grid.tilted)
fs.OVERRIDES.clear(); fs.PRESS.clear()


# ===================== v3.3: facies modelling =====================
p = S.proj()
fs.OVERRIDES.clear(); fs.PRESS.clear(); fs.MESSAGES.clear()
p.stochastic = {}
p.grid = p.grid if p.grid is not None else None
fs.OVERRIDES.update({"sx_c1": 0.6, "sx_c2": 0.3, "sx_c3": 0.2, "sx_pm": "field"})
ok("facies tab renders with defaults", page(vprops.render) and not errors() and p.facies.get("method") == "truncated_gaussian", errors())
fs.PRESS.add("Run facies model")
ok("TGS run stores a discrete FACIES property with a legend", page(vprops.render) and "FACIES" in p.properties and p.properties["FACIES"].kind == "discrete"
   and p.properties["FACIES"].legend.get("2") == "Heterolithic" and not errors(), errors())
fs.PRESS.clear()
ok("QC (proportions, vertical curves, map) renders", page(vprops.render) and not errors(), errors())
fs.PRESS.add("Create PORO, PERMX/Y/Z, NTG from facies")
ok("petrophysics from facies stored", page(vprops.render) and p.properties["PORO"].source == "facies" and p.properties["NTG"].source == "facies" and not errors(), errors())
fs.PRESS.clear()
fs.OVERRIDES["fa_meth"] = "objects"
fs.PRESS.add("Run facies model")
ok("object modelling runs from the page", page(vprops.render) and p.facies["method"] == "objects" and not errors(), errors())
fs.PRESS.clear()
fs.OVERRIDES["fa_nf"] = 4
fs.OVERRIDES["fa_meth"] = "truncated_gaussian"
fs.PRESS.add("Run facies model")
ok("changing the number of facies rebuilds the setup and runs", page(vprops.render) and len(p.facies["facies"]) == 4 and set(np.unique(p.properties["FACIES"].values)) <= {1, 2, 3, 4} and not errors(), errors())
fs.PRESS.clear(); fs.OVERRIDES.clear()
p4_ = pj.from_bytes(pj.to_bytes(p))
ok("facies setup + FACIES property survive save/load", p4_.facies["method"] == "truncated_gaussian" and p4_.properties["FACIES"].legend.get("1") == "Shale")


# ===================== v3.3: plurigaussian, indicator simulation, volume weighting =====================
p = S.proj()
fs.OVERRIDES.clear(); fs.PRESS.clear(); fs.MESSAGES.clear()
fs.OVERRIDES.update({"sx_c1": 0.6, "sx_c2": 0.3, "sx_c3": 0.2, "sx_pm": "field", "fa_nf": 3})
fs.OVERRIDES["fa_meth"] = "plurigaussian"
fs.PRESS.add("Run facies model")
ok("plurigaussian from the page (rule table, G2 variogram)", page(vprops.render) and p.facies["method"] == "plurigaussian" and not errors()
   and set(np.unique(p.properties["FACIES"].values[p.grid.actnum > 0])) <= {1, 2, 3}, errors())
fs.PRESS.clear()
fs.OVERRIDES["fa_n1"] = 2
fs.OVERRIDES["fa_n2"] = 3
fs.PRESS.add("Run facies model")
ok("rule table can be resized to 2 x 3", page(vprops.render) and np.asarray(p.facies["rule"]).shape == (2, 3), (errors(), p.facies["rule"]))
fs.PRESS.clear(); fs.OVERRIDES.pop("fa_n1"); fs.OVERRIDES.pop("fa_n2")
fs.OVERRIDES["fa_meth"] = "indicator"
fs.OVERRIDES["fa_nmax"] = 12
fs.PRESS.add("Run facies model")
ok("indicator simulation from the page", page(vprops.render) and p.facies["method"] == "indicator" and p.facies["nmax"] == 12 and not errors(), errors())
fs.PRESS.clear()
fs.OVERRIDES["fa_meth"] = "truncated_gaussian"
fs.OVERRIDES["fa_vw"] = False
fs.PRESS.add("Run facies model")
ok("TGS with cell-count proportions (volume weighting off)", page(vprops.render) and p.facies["vol_weight"] is False and not errors(), errors())
fs.PRESS.clear(); fs.OVERRIDES.clear()
p5_ = pj.from_bytes(pj.to_bytes(p))
ok("rule, weights and G2 settings survive save/load", p5_.facies["vol_weight"] is False and "rule" in p5_.facies and "major2" in p5_.facies["zones"][0])

fs.OVERRIDES.clear(); fs.PRESS.clear()
print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
