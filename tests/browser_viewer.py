"""Headless-Chrome test of the WebGL viewer (software GL via SwiftShader) with a scene built from the demo."""
import http.server, json, os, socketserver, sys, threading
import numpy as np
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMP = os.path.join(ROOT, "components")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import fake_streamlit as fs
fs.install()
from core.demo import build_demo
from core.workflow import run_workflow
from core.cpgrid import build_grid
from ui.scene import Scene

SHOT = os.environ.get("SHOT_DIR", "/tmp")
HOST = """<!doctype html><body style="margin:0"><iframe id="f" src="viewer3d/index.html" style="width:1200px;height:700px;border:0"></iframe>
<script>window.msgs=[];window.addEventListener('message',e=>{if(e.data&&e.data.isStreamlitMessage)window.msgs.push(e.data);});
function render(a){document.getElementById('f').contentWindow.postMessage({type:'streamlit:render',args:a,disabled:false,theme:{}},'*');}</script></body>"""
open(os.path.join(COMP, "_host_viewer3d.html"), "w").write(HOST)


class Q(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=COMP, **k)

    def log_message(self, *a):
        pass


socketserver.TCPServer.allow_reuse_address = True
httpd = socketserver.TCPServer(("127.0.0.1", 0), Q)
PORT = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()

p = build_demo()
st = run_workflow(p.steps, p.surfaces, p.faults, p.tops, p.lattice)
grid = build_grid(st, p.zones, 200, 200, 0.1, bounds=p.grid_bounds(), boundary=p.boundary_poly())
sc = Scene((p.lattice.xori, p.lattice.yori))
zs = [np.nanmin(s.z) for s in p.surfaces.values()], [np.nanmax(s.z) for s in p.surfaces.values()]
for n in ("Top_Overburden", "BCU", "Top_Reservoir"):
    sc.surface(p.surfaces[n], visible=(n == "Top_Reservoir"), color_by_depth=True)
sc.faults(p.faults, min(zs[0]), max(zs[1]))
sc.polygon(p.polygons["Boundary"], ref=p.surfaces["Top_Reservoir"])
hc = {"Top_Reservoir": "#F46036", "Base_Reservoir": "#6A4C93"}
for w in p.wells.values():
    sc.well(w, p.tops, radius=30, hcolors=hc, z_start=1200)
sc.grid(grid, "Zone", name="3D grid (zones)")
d = sc.to_dict()
print("scene objects:", len(d["objects"]), " payload MB:", round(len(json.dumps(d)) / 1e6, 2))

results, errors = [], []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))


with sync_playwright() as pw:
    br = pw.chromium.launch(executable_path="/usr/bin/google-chrome",
                            args=["--no-sandbox", "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
                                  "--ignore-gpu-blocklist", "--enable-webgl"])
    pg = br.new_page(viewport={"width": 1220, "height": 720})
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" and "404" not in m.text else None)
    pg.goto("http://127.0.0.1:%d/_host_viewer3d.html" % PORT)
    pg.wait_for_timeout(500)
    pg.evaluate("a=>render(a)", dict(scene=d, rev="r1", cam_key=sc.cam_key, height=700, ve=3.0))
    pg.wait_for_timeout(1500)
    fr = pg.frame_locator("#f")
    f = pg.frames[1]
    check("viewer announces itself", any(m["type"] == "streamlit:componentReady" for m in pg.evaluate("window.msgs")))
    nobj = f.evaluate("window.__viewer.objs().length")
    check("all objects loaded", nobj == len(d["objects"]), f"{nobj}")
    gpu_ok = f.evaluate("window.__viewer.objs().every(o=>o.gpu)")
    check("every object has GPU buffers", gpu_ok)
    check("no JS / WebGL errors on load", not errors, "; ".join(errors[:3]))
    tree_rows = f.evaluate("document.querySelectorAll('#tree .row').length")
    check("object tree rows", tree_rows == nobj, f"{tree_rows}")
    groups = f.evaluate("[...document.querySelectorAll('#tree .grp')].map(e=>e.textContent)")
    check("tree groups", {"Surfaces", "Faults", "Polygons", "Wells", "3D grid"} <= set(groups), str(groups))

    def px():
        return pg.screenshot(clip=dict(x=230, y=0, width=980, height=700))
    from PIL import Image
    import io

    def nonbg(png):
        im = np.asarray(Image.open(io.BytesIO(png)).convert("RGB")).astype(int)
        return float((np.abs(im - 255).sum(axis=2) > 30).mean())

    img1 = px()
    open(f"{SHOT}/viewer_iso.png", "wb").write(img1)
    check("scene renders something (iso)", nonbg(img1) > 0.04, f"{nonbg(img1):.3f} covered")

    # orbit with mouse drag
    az0 = f.evaluate("window.__viewer.cam.az")
    pg.mouse.move(700, 350); pg.mouse.down(); pg.mouse.move(820, 330, steps=6); pg.mouse.up()
    az1 = f.evaluate("window.__viewer.cam.az")
    check("mouse drag orbits", abs(az1 - az0) > 0.3, f"{az0:.2f} -> {az1:.2f}")
    d0 = f.evaluate("window.__viewer.cam.dist")
    pg.mouse.move(700, 350); pg.mouse.wheel(0, -400)
    d1 = f.evaluate("window.__viewer.cam.dist")
    check("wheel zooms in", d1 < d0 * 0.8, f"{d0:.0f} -> {d1:.0f}")
    t0 = f.evaluate("window.__viewer.cam.t.slice()")
    pg.keyboard.down("Shift"); pg.mouse.move(700, 350); pg.mouse.down(); pg.mouse.move(760, 380, steps=5); pg.mouse.up(); pg.keyboard.up("Shift")
    t1 = f.evaluate("window.__viewer.cam.t.slice()")
    check("shift-drag pans", np.linalg.norm(np.array(t1) - np.array(t0)) > 10, f"{t0} -> {t1}")
    pg.mouse.dblclick(700, 350)
    check("double click fits", abs(f.evaluate("window.__viewer.cam.dist") - d1) > 1)

    # views
    f.click("#vTop")
    check("top view elevation", f.evaluate("window.__viewer.cam.el") > 1.5)
    pg.wait_for_timeout(200)
    top = px(); open(f"{SHOT}/viewer_top.png", "wb").write(top)
    f.click("#vN")
    check("section view elevation", f.evaluate("window.__viewer.cam.el") < 0.1)
    f.click("#vIso")
    pg.wait_for_timeout(200)

    # visibility + opacity
    def arr(png):
        return np.asarray(Image.open(io.BytesIO(png)).convert("RGB")).astype(int)
    before = arr(px())
    f.evaluate("window.__viewer.objs().forEach(o=>{if(o.def.group==='3D grid')o.st.visible=false;});window.__viewer.render()")
    after = arr(px())
    diff = float((np.abs(before - after).sum(axis=2) > 40).mean())
    check("hiding the grid changes the picture", diff > 0.03, f"{diff:.3f} of pixels changed")
    f.evaluate("window.__viewer.objs().forEach(o=>{if(o.def.group==='3D grid')o.st.visible=true;});window.__viewer.render()")
    f.click("#tree .row >> nth=0")
    check("row click selects", f.evaluate("document.querySelectorAll('#tree .row.sel').length") == 1)
    cb = f.locator("#tree .row input[type=checkbox]").first
    was = cb.is_checked(); cb.click()
    check("checkbox toggles visibility", f.evaluate("window.__viewer.objs()[0].st.visible") == (not was))
    cb.click()

    # vertical exaggeration
    f.evaluate("document.getElementById('ve').value=8;document.getElementById('ve').dispatchEvent(new Event('input'))")
    check("VE slider updates", f.evaluate("window.__viewer.opt.ve") == 8)
    w_ok = f.evaluate("window.__viewer.objs().filter(o=>o.def.type==='well').every(o=>o.gpu&&o.gpu.nv>=20)")
    check("wells rebuilt on VE change", w_ok)
    pg.wait_for_timeout(200)
    open(f"{SHOT}/viewer_ve8.png", "wb").write(px())

    # wireframe + dark + labels
    f.check("#wire"); f.check("#dark"); f.check("#tl")
    pg.wait_for_timeout(300)
    wimg = px(); open(f"{SHOT}/viewer_wire_dark.png", "wb").write(wimg)
    check("wireframe draws (grid wire buffers)", f.evaluate("window.__viewer.objs().some(o=>o.gpu&&o.gpu.bWire)"))
    im = np.asarray(Image.open(io.BytesIO(wimg)).convert("RGB")).astype(int)
    check("dark background applied", im[5, 5].sum() < 150, str(im[5, 5]))
    f.uncheck("#dark"); f.uncheck("#wire")

    # legend
    leg = f.evaluate("document.getElementById('legend').style.display+'|'+document.getElementById('legend').textContent")
    check("legend shown", leg.startswith("block") and len(leg) > 12, leg[:60])

    # camera persists on rerender with same cam_key but new rev
    f.evaluate("window.__viewer.setView(2.0,0.3)")
    az = f.evaluate("window.__viewer.cam.az")
    d2 = dict(d); d2["objects"] = d["objects"][:-1]
    pg.evaluate("a=>render(a)", dict(scene=d2, rev="r2", cam_key=sc.cam_key, height=700, ve=3.0))
    pg.wait_for_timeout(600)
    check("camera kept across re-render", abs(f.evaluate("window.__viewer.cam.az") - az) < 1e-6)
    check("re-render replaces objects", f.evaluate("window.__viewer.objs().length") == len(d2["objects"]))
    hidden = f.evaluate("window.__viewer.ostate['Surfaces/Top_Overburden'].visible")
    check("visibility state kept across re-render", hidden is False)
    pg.evaluate("a=>render(a)", dict(scene=d2, rev="r3", cam_key="other", height=700, ve=3.0))
    pg.wait_for_timeout(600)
    check("camera refit when extent changes", abs(f.evaluate("window.__viewer.cam.az") - az) < 1e-6 and f.evaluate("window.__viewer.cam.dist") > 100)
    check("no JS errors at end", not errors, "; ".join(errors[:3]))
    br.close()

os.remove(os.path.join(COMP, "_host_viewer3d.html"))
httpd.shutdown()
bad = results.count(False)
print(f"\n{len(results) - bad}/{len(results)} passed")
sys.exit(1 if bad else 0)
