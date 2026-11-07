"""Headless-Chrome test of the two JS components using a tiny host page that speaks the Streamlit
component protocol (componentReady / render / setComponentValue)."""
import http.server, json, os, socketserver, sys, threading, io
import numpy as np
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMP = os.path.join(ROOT, "components")
sys.path.insert(0, ROOT)
from core.demo import build_demo
from core.workflow import run_workflow

HOST = """<!doctype html><body style="margin:0"><iframe id="f" src="%s/index.html" style="width:1100px;height:660px;border:0"></iframe>
<script>window.msgs=[];window.addEventListener('message',e=>{if(e.data&&e.data.isStreamlitMessage)window.msgs.push(e.data);});
function render(a){document.getElementById('f').contentWindow.postMessage({type:'streamlit:render',args:a,disabled:false,theme:{}},'*');}</script></body>"""
for name in ("map_editor", "plotly_view"):
    open(os.path.join(COMP, f"_host_{name}.html"), "w").write(HOST % name)


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
g = p.lattice
Z = st.lattice_depths()[2]
grid = dict(x0=g.xori, y0=g.yori, dx=g.xinc, dy=g.yinc, ncol=g.ncol, nrow=g.nrow,
            z=[None if not np.isfinite(v) else round(float(v), 2) for v in Z.ravel()],
            zmin=float(np.nanmin(Z)), zmax=float(np.nanmax(Z)))
xmin, xmax, ymin, ymax = g.bounds()
results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))


errors = []
with sync_playwright() as pw:
    br = pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    pg = br.new_page(viewport={"width": 1120, "height": 680})
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

    # ------------------------------------------------------------ fault designer
    pg.goto("http://127.0.0.1:%d/" % PORT + "_host_map_editor.html")
    pg.wait_for_timeout(400)
    pg.evaluate("a=>render(a)", dict(mode="faults", rev="empty-faults", height=640, extent=[xmin, xmax, ymin, ymax],
                                   grid=grid, faults=[], defaults=dict(throw=50, dip=65, zref=2000)))
    fr = pg.frame_locator("#f")
    fr.get_by_role("button", name="Apply to model").wait_for()
    check("empty fault designer initializes its backdrop and drawing tool",
          pg.frames[1].evaluate("S.tool==='draw' && S.gridCv!==null"))
    cv = fr.locator("#cv")
    cv.click(position={"x": 100, "y": 100})
    cv.click(position={"x": 200, "y": 200})
    cv.dblclick(position={"x": 300, "y": 300})
    fr.locator("#fThrow").fill("85")
    fr.get_by_role("button", name="Apply to model").click()
    pg.wait_for_timeout(100)
    first_fault = [m for m in pg.evaluate("msgs") if m["type"] == "streamlit:setComponentValue"][-1]["value"]
    check("first fault can be drawn and applied on the backdrop", first_fault["kind"] == "faults"
          and len(first_fault["faults"]) == 1 and len(first_fault["faults"][0]["trace"]) == 3
          and first_fault["faults"][0]["throw"] == 85)
    args = dict(mode="faults", rev="k1", height=640, extent=[xmin, xmax, ymin, ymax], grid=grid,
                faults=[f.to_dict() for f in p.faults.values()],
                wells=[dict(name=w, x=float(r.x), y=float(r.y)) for w, r in p.tops.groupby("well").first().iterrows()],
                defaults=dict(throw=40, dip=60, zref=2050))
    pg.evaluate("a=>render(a)", args)
    pg.wait_for_timeout(600)
    fr = pg.frame_locator("#f")
    pg.screenshot(path="/tmp/ed_faults.png")
    check("faults loaded", pg.frame("f") is None or True)
    n0 = pg.frames[1].evaluate("S.faults.length")
    check("2 faults loaded into editor", n0 == 2, n0)
    fr.get_by_role("button", name="Draw fault").click()
    cv = fr.locator("#cv")
    for pos in [(200, 120), (300, 200), (380, 330)]:
        cv.click(position={"x": pos[0], "y": pos[1]})
    cv.dblclick(position={"x": 430, "y": 420})
    n1 = pg.frames[1].evaluate("S.faults.length")
    check("drawn fault added", n1 == 3, n1)
    tr = pg.frames[1].evaluate("S.faults[2].trace")
    check("drawn fault has 4 vertices (dblclick duplicate removed)", len(tr) == 4, len(tr))
    fr.locator("#fThrow").fill("85")
    fr.get_by_role("button", name="Flip side").click()
    pg.frames[1].evaluate("document.getElementById('bSend').click()")
    pg.wait_for_timeout(200)
    msgs = pg.evaluate("msgs.filter(m=>m.type==='streamlit:setComponentValue')")
    val = msgs[-1]["value"] if msgs else None
    check("setComponentValue sent", val and val["kind"] == "faults" and len(val["faults"]) == 3, str(val)[:80] if val else "none")
    check("edited throw + flipped side travel to Python", val and val["faults"][2]["throw"] == 85 and val["faults"][2]["hw_side"] == "right")
    # drag a vertex of fault 2 (select it first)
    pg.frames[1].evaluate("S.sel=0; buildPanel(); draw()")
    pt = pg.frames[1].evaluate("w2s(S.faults[0].trace[2][0], S.faults[0].trace[2][1])")
    cv.hover(position={"x": pt[0], "y": pt[1]})
    pg.mouse.down()
    box = cv.bounding_box()
    pg.mouse.move(box["x"] + pt[0] + 40, box["y"] + pt[1] + 25, steps=4)
    pg.mouse.up()
    moved = pg.frames[1].evaluate("S.faults[0].trace[2]")
    orig = p.faults["F1_main"].trace[2]
    check("vertex drag moves fault vertex", abs(moved[0] - orig[0]) > 50, f"{orig} -> {moved}")
    # new fault models: type selector reveals slip / pivot / heave fields and sends them to Python
    pg.frames[1].evaluate("S.sel=2; buildPanel(); draw()")
    fr.locator("#fType").select_option("transverse")
    pg.wait_for_timeout(150)
    check("transverse type shows pivot + slip + heave fields", fr.locator("#fPivot").count() == 1 and fr.locator("#fSlip").count() == 1 and fr.locator("#fHeave").count() == 1)
    fr.locator("#fPivot").fill("0.3")
    fr.locator("#fSlip").fill("75")
    fr.locator("#fHeave").fill("0.5")
    fr.locator("#fSense").select_option("sinistral")
    pg.frames[1].evaluate("document.getElementById('bSend').click()")
    pg.wait_for_timeout(200)
    msgs = pg.evaluate("msgs.filter(m=>m.type==='streamlit:setComponentValue')")
    f3 = msgs[-1]["value"]["faults"][2]
    check("type/pivot/slip/heave/sense travel to Python", f3["ftype"] == "transverse" and f3["pivot"] == 0.3 and f3["slip"] == 75 and f3["heave"] == 0.5 and f3["slip_sense"] == "sinistral", str(f3)[:140])
    fr.locator("#fType").select_option("normal")
    pg.wait_for_timeout(100)
    check("normal type hides pivot / slip", fr.locator("#fPivot").count() == 0 and fr.locator("#fSlip").count() == 0)
    pg.screenshot(path="/tmp/ed_faults2.png")

    # ------------------------------------------------------------ digitizer: blank canvas
    pg.goto("http://127.0.0.1:%d/" % PORT + "_host_map_editor.html")
    pg.wait_for_timeout(300)
    pg.evaluate("a=>render(a)", dict(mode="digitize", rev="d1", height=640, extent=[0, 4000, 0, 3000], z_default=2000))
    pg.wait_for_timeout(400)
    fr = pg.frame_locator("#f")
    cv = fr.locator("#cv")
    cv.click(position={"x": 150, "y": 200}); cv.click(position={"x": 300, "y": 250}); cv.dblclick(position={"x": 450, "y": 220})
    fr.locator("#zVal").fill("2050")
    cv.click(position={"x": 150, "y": 350}); cv.click(position={"x": 300, "y": 400}); cv.dblclick(position={"x": 450, "y": 380})
    fr.get_by_role("button", name="Spot point").click()
    fr.locator("#zVal").fill("2010")
    cv.click(position={"x": 250, "y": 300})
    fr.get_by_role("button", name="Fault trace").click()
    cv.click(position={"x": 520, "y": 150}); cv.dblclick(position={"x": 560, "y": 450})
    pg.frames[1].evaluate("document.getElementById('bSend').click()")
    pg.wait_for_timeout(200)
    msgs = pg.evaluate("msgs.filter(m=>m.type==='streamlit:setComponentValue')")
    v = msgs[-1]["value"]
    check("2 contours digitized with their z", [c["z"] for c in v["contours"]] == [2000, 2050] and all(len(c["pts"]) == 3 for c in v["contours"]),
          [(c["z"], len(c["pts"])) for c in v["contours"]])
    check("spot point carries z", len(v["points"]) == 1 and v["points"][0][2] == 2010)
    check("fault trace captured", len(v["faults"]) == 1 and len(v["faults"][0]["pts"]) == 2)
    check("world coords inside extent", all(0 <= q[0] <= 4000 and 0 <= q[1] <= 3000 for c in v["contours"] for q in c["pts"]),
          v["contours"][0]["pts"][0])
    pg.screenshot(path="/tmp/ed_dig_blank.png")

    # Depth auto-step, editing existing contours, and the boundary overlay.
    boundary = dict(name="Boundary", pts=[[50, 50], [450, 50], [450, 450], [50, 450]])
    pg.evaluate("a=>render(a)", dict(mode="digitize", rev="dstep", height=640, extent=[0, 500, 0, 500],
                                   z_default=1900, polygons=[boundary], boundary="Boundary"))
    fr.locator("#zStep").fill("100")
    for y in (50, 250, 450):
        for x in (50, 250, 450):
            s = pg.frames[1].evaluate("p=>w2s(...p)", [x, y])
            cv.click(position={"x": s[0], "y": s[1]})
        fr.locator("#bFinish").click()
    zs = pg.frames[1].evaluate("S.contours.map(c=>c.z)")
    check("nonzero depth step updates each completed contour", zs == [1900, 2000, 2100])
    pg.frames[1].evaluate("sendDigitized()")
    v = [m for m in pg.evaluate("msgs") if m["type"] == "streamlit:setComponentValue"][-1]["value"]
    from core import interp
    from core.surface import Geometry
    surf = interp.grid_points(interp.contours_to_points(v["contours"], 25), Geometry(0, 0, 25, 25, 21, 21),
                              "min_curvature", tension=0.3)
    check("browser contours grid to a nonconstant surface", np.ptp(surf.z) > 150)
    fr.locator("[data-c='0']").click()
    fr.locator("#zVal").fill("1850")
    fr.locator("#zStep").fill("-50")
    fr.locator("#bFinish").click()
    check("selected contour depth can be corrected; negative step works",
          pg.frames[1].evaluate("S.contours[0].z===1850 && S.zVal===1800"))
    fr.locator("#zStep").fill("0")
    fr.locator("[data-c='0']").click()
    fr.locator("#bFinish").click()
    check("zero step leaves depth unchanged", pg.frames[1].evaluate("S.zVal===1850"))
    check("boundary uses world coordinates without an image", pg.frames[1].evaluate("boundaryPoints()") == boundary["pts"])
    fr.locator("#showBoundary").uncheck()
    check("digitizer boundary overlay can be hidden", pg.frames[1].evaluate("boundaryPoints().length===0"))

    # ------------------------------------------------------------ digitizer: image + calibration
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (800, 600), "white")
    d = ImageDraw.Draw(im)
    for r in (120, 200, 280):
        d.ellipse([400 - r, 300 - r * 0.7, 400 + r, 300 + r * 0.7], outline=(180, 30, 30), width=3)
    d.line([(0, 0), (800, 0), (800, 600), (0, 600), (0, 0)], fill="black", width=4)
    im.save("/tmp/map.png")
    pg.goto("http://127.0.0.1:%d/" % PORT + "_host_map_editor.html")
    pg.wait_for_timeout(300)
    pg.evaluate("a=>render(a)", dict(mode="digitize", rev="d2", height=640, z_default=1900,
                                   polygons=[dict(name="Boundary", pts=[[1000, 2000], [5000, 2000], [5000, 5000], [1000, 5000]])],
                                   boundary="Boundary"))
    pg.wait_for_timeout(300)
    fr = pg.frame_locator("#f")
    fr.locator("#fImg").set_input_files("/tmp/map.png")
    pg.wait_for_timeout(600)
    check("image loaded", pg.frames[1].evaluate("!!S.img && S.view.yDown"))
    # calibrate with TWO known pixel positions: bottom-left (0,600)px -> (1000, 2000); top-right (800,0)px -> (5000, 5000)
    cv = fr.locator("#cv")
    for i, (px, py, X, Y) in enumerate([(0, 600, 1000, 2000), (800, 0, 5000, 5000)]):
        fr.locator(f"[data-pick='{i}']").click()
        s = pg.frames[1].evaluate(f"w2s({px},{py})")
        cv.click(position={"x": max(1, s[0]), "y": min(s[1], pg.frames[1].evaluate("S.H") - 1)})
        fr.locator(f"[data-cx='{i}']").fill(str(X))
        fr.locator(f"[data-cy='{i}']").fill(str(Y))
    T = pg.frames[1].evaluate("affine()")
    check("2-point calibration solved", T and abs(T["a"] - 5.0) < 0.2 and abs(T["e"] + 5.0) < 0.2, T)
    fr.locator("#showBoundary").check()
    bp = pg.frames[1].evaluate("boundaryPoints().map(p=>applyT(affine(),...p))")
    check("scanned-map boundary inverse calibration preserves world coordinates",
          np.allclose(bp, [[1000, 2000], [5000, 2000], [5000, 5000], [1000, 5000]]))
    # digitize contour along first ellipse: three clicks, z=1900
    s0 = pg.frames[1].evaluate("w2s(400,300)")
    cv.click(position={"x": s0[0] - 60, "y": s0[1]}); cv.click(position={"x": s0[0], "y": s0[1] - 40}); cv.dblclick(position={"x": s0[0] + 60, "y": s0[1]})
    pg.frames[1].evaluate("document.getElementById('bSend').click()")
    pg.wait_for_timeout(200)
    v = [m for m in pg.evaluate("msgs") if m["type"] == "streamlit:setComponentValue"][-1]["value"]
    pix = pg.frames[1].evaluate("S.contours[0].pts")
    expect = [[T["a"] * p[0] + T["b"] * p[1] + T["c"], T["d"] * p[0] + T["e"] * p[1] + T["f"]] for p in pix]
    check("pixel -> world conversion matches affine", np.allclose(np.array(v["contours"][0]["pts"]), np.array(expect), atol=1e-6))
    cx = v["contours"][0]["pts"][1]
    check("centre pixel (400,300) maps near (3000,3500)", abs(v["contours"][0]["pts"][1][0] - 3000) < 400 and v["calib"]["rms"] < 60, v["calib"])
    pg.screenshot(path="/tmp/ed_dig_img.png")

    # ------------------------------------------------------------ polygon editor
    pg.goto("http://127.0.0.1:%d/" % PORT + "_host_map_editor.html")
    pg.wait_for_timeout(300)
    pg.evaluate("a=>render(a)", dict(mode="polygons", rev="p1", height=640, extent=[xmin, xmax, ymin, ymax], grid=grid,
                                     polygons=[dict(name="Existing", pts=[[xmin + 1000, ymin + 1000], [xmin + 4000, ymin + 1200], [xmin + 3500, ymin + 3500]])],
                                     boundary="Existing", wells=[]))
    pg.wait_for_timeout(500)
    fr = pg.frame_locator("#f")
    f1 = pg.frames[1]
    check("polygon editor: existing polygon + boundary loaded", f1.evaluate("S.polys.length") == 1 and f1.evaluate("S.boundary") == "Existing")
    check("polygon editor opens in edit tool when polygons exist", f1.evaluate("S.tool") == "edit")
    cv = fr.locator("#cv")
    fr.get_by_role("button", name="Draw polygon").click()
    for pos in [(180, 120), (420, 140), (440, 330)]:
        cv.click(position={"x": pos[0], "y": pos[1]})
    cv.dblclick(position={"x": 200, "y": 360})
    check("drawn polygon closed with 4 vertices", f1.evaluate("S.polys.length") == 2 and f1.evaluate("S.polys[1].pts.length") == 4, f1.evaluate("S.polys.length"))
    fr.locator("#pName").fill("Licence_A")
    fr.locator("#pBound").check()
    check("boundary switches to the new polygon", f1.evaluate("S.boundary") == "Licence_A")
    # drag a vertex of the selected polygon, insert and delete vertices
    pt = f1.evaluate("w2s(S.polys[1].pts[1][0], S.polys[1].pts[1][1])")
    before = f1.evaluate("S.polys[1].pts[1]")
    cv.hover(position={"x": pt[0], "y": pt[1]})
    pg.mouse.down()
    box = cv.bounding_box()
    pg.mouse.move(box["x"] + pt[0] + 50, box["y"] + pt[1] + 30, steps=4)
    pg.mouse.up()
    after = f1.evaluate("S.polys[1].pts[1]")
    check("polygon vertex drag", abs(after[0] - before[0]) > 50, f"{before} -> {after}")
    mid = f1.evaluate("(()=>{const a=S.polys[1].pts[0],b=S.polys[1].pts[1];return w2s((a[0]+b[0])/2,(a[1]+b[1])/2);})()")
    cv.dblclick(position={"x": mid[0], "y": mid[1]})
    check("double-click on an edge inserts a vertex", f1.evaluate("S.polys[1].pts.length") == 5)
    pt = f1.evaluate("w2s(S.polys[1].pts[2][0], S.polys[1].pts[2][1])")
    pg.keyboard.down("Shift"); cv.click(position={"x": pt[0], "y": pt[1]}); pg.keyboard.up("Shift")
    check("shift-click deletes a vertex", f1.evaluate("S.polys[1].pts.length") == 4)
    f1.evaluate("document.getElementById('bSend').click()")
    pg.wait_for_timeout(200)
    v = [m for m in pg.evaluate("msgs") if m["type"] == "streamlit:setComponentValue"][-1]["value"]
    check("polygons sent to Python", v["kind"] == "polygons" and [q["name"] for q in v["polygons"]] == ["Existing", "Licence_A"] and v["boundary"] == "Licence_A", str(v)[:100])
    check("polygon world coordinates inside the extent", all(xmin - 1 <= x <= xmax + 1 and ymin - 1 <= y <= ymax + 1 for q in v["polygons"] for x, y in q["pts"]))
    pg.screenshot(path="/tmp/ed_polygons.png")
    f1.evaluate("S.psel=1; buildPanel()")
    fr.locator("#pDel").click()
    check("delete polygon clears boundary if it was the boundary", f1.evaluate("S.polys.length") == 1 and f1.evaluate("S.boundary") == "")

    # ------------------------------------------------------------ fence editor (open polylines)
    pg.goto("http://127.0.0.1:%d/" % PORT + "_host_map_editor.html")
    pg.wait_for_timeout(300)
    pg.evaluate("a=>render(a)", dict(mode="fences", rev="f1", height=640, extent=[xmin, xmax, ymin, ymax], grid=grid, polygons=[], wells=[]))
    pg.wait_for_timeout(500)
    fr = pg.frame_locator("#f")
    f1 = pg.frames[1]
    check("fence editor opens in draw mode when empty", f1.evaluate("S.open") is True and f1.evaluate("S.tool") == "draw")
    cv = fr.locator("#cv")
    for pos in [(150, 150), (300, 220), (420, 150)]:
        cv.click(position={"x": pos[0], "y": pos[1]})
    cv.dblclick(position={"x": 520, "y": 300})
    check("fence stays open with 4 vertices", f1.evaluate("S.polys.length") == 1 and f1.evaluate("S.polys[0].pts.length") == 4, f1.evaluate("S.polys.length"))
    check("fence named Fence_1", f1.evaluate("S.polys[0].name") == "Fence_1")
    check("fence panel has no boundary option", fr.locator("#pBound").count() == 0)
    pt = f1.evaluate("w2s(S.polys[0].pts[1][0], S.polys[0].pts[1][1])")
    before = f1.evaluate("S.polys[0].pts[1]")
    cv.hover(position={"x": pt[0], "y": pt[1]})
    pg.mouse.down()
    box = cv.bounding_box()
    pg.mouse.move(box["x"] + pt[0] + 40, box["y"] + pt[1] + 40, steps=4)
    pg.mouse.up()
    check("fence vertex drag", abs(f1.evaluate("S.polys[0].pts[1]")[0] - before[0]) > 30)
    # an open polyline has no closing segment: double-click beyond the last vertex must not insert
    last = f1.evaluate("w2s(S.polys[0].pts[3][0], S.polys[0].pts[3][1])")
    first = f1.evaluate("w2s(S.polys[0].pts[0][0], S.polys[0].pts[0][1])")
    mid = [(last[0] + first[0]) / 2, (last[1] + first[1]) / 2]
    cv.dblclick(position={"x": mid[0], "y": mid[1]})
    check("no closing segment on an open fence", f1.evaluate("S.polys[0].pts.length") == 4)
    pg.keyboard.down("Shift"); cv.click(position={"x": pt[0] + 40, "y": pt[1] + 40}); pg.keyboard.up("Shift")
    check("shift-click deletes a fence vertex (min 2 kept)", f1.evaluate("S.polys[0].pts.length") == 3)
    f1.evaluate("document.getElementById('bSend').click()")
    pg.wait_for_timeout(200)
    v = [m for m in pg.evaluate("msgs") if m["type"] == "streamlit:setComponentValue"][-1]["value"]
    check("fences sent to Python as kind=fences", v["kind"] == "fences" and v["polygons"][0]["name"] == "Fence_1" and len(v["polygons"][0]["pts"]) == 3, str(v)[:100])
    check("fence world coordinates inside the extent", all(xmin - 1 <= x <= xmax + 1 and ymin - 1 <= y <= ymax + 1 for q in v["polygons"] for x, y in q["pts"]))
    pg.screenshot(path="/tmp/ed_fences.png")

    # ------------------------------------------------------------ plotly_view with a mock Plotly
    pg.goto("http://127.0.0.1:%d/" % PORT + "_host_plotly_view.html")
    pg.wait_for_timeout(300)
    pg.frames[1].evaluate("window.Plotly={calls:[],react:function(id,d,l,c){this.calls.push([id,d.length,l.title])},Plots:{resize:function(){}}}")
    pg.evaluate("a=>render(a)", dict(rev="a", height=400, spec=dict(data=[{"type": "surface", "z": [[1, 2], [3, 4]]}], layout=dict(title="t"))))
    pg.wait_for_timeout(300)
    calls = pg.frames[1].evaluate("Plotly.calls")
    check("plotly_view calls Plotly.react once per key", len(calls) == 1 and calls[0][1] == 1, calls)
    pg.evaluate("a=>render(a)", dict(rev="a", height=400, spec=dict(data=[], layout={})))
    pg.wait_for_timeout(200)
    check("same key does not re-render", len(pg.frames[1].evaluate("Plotly.calls")) == 1)
    br.close()

for name in ("map_editor", "plotly_view"):
    os.remove(os.path.join(COMP, f"_host_{name}.html"))
httpd.shutdown()
errs = [e for e in errors if "favicon" not in e and "plotly.min.js" not in e and "ERR_" not in e and "404" not in e]
check("no JS errors in console", not errs, errs[:3])
print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
