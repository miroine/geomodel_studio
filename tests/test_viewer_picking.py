"""Real exterior payloads, raw property inspection and dependency-free Chrome picking."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import fake_streamlit as fs
fs.install()
from core.cpgrid import CPGrid, ZoneSpec
from ui.scene import Scene, grid_property, WEBVIZ_PHYSICS, WEBVIZ_CATEGORIES
from ui.components import viewer3d


def fixture():
    nk, nj, ni = 3, 3, 4
    zc = np.empty((nk, 2, nj, 2, ni, 2))
    for k in range(nk):
        zc[k, 0] = 10 + k * 10
        zc[k, 1] = 20 + k * 10
    act = np.ones((nk, nj, ni), int)
    act[0, 2, 3] = 0
    g = CPGrid(ni, nj, nk, np.arange(ni + 1) * 20., np.arange(nj + 1) * 20.,
               zc, act, np.array([0, 1, 1]), [ZoneSpec("A", "T", "M"), ZoneSpec("B", "M", "B")],
               np.ones((nj, ni), int), [])
    values = np.arange(g.ncells).reshape(act.shape).astype(float) + 100
    props = {"PERMX": SimpleNamespace(values=values, kind="continuous", unit="mD")}
    return g, props


def decode(s, dtype):
    return np.frombuffer(base64.b64decode(s), dtype=dtype)


class ViewerPickingTests(unittest.TestCase):
    def test_exterior_ids_and_scalar_follow_triangle_order(self):
        g, props = fixture()
        for i0, j0, mask in ((0, 0, None), (1, 1, np.array([False, True, False])),
                             (2, 0, np.array([True, False, True]))):
            v, t, scalar, ids = g.exterior_faces(i0, j0, props["PERMX"].values,
                                                layer_mask=mask, return_cell_ids=True)
            self.assertEqual(len(t), len(ids))
            np.testing.assert_array_equal(scalar, props["PERMX"].values.ravel()[ids])
            kk, jj, ii = np.unravel_index(ids, g.actnum.shape)
            self.assertTrue(np.all((ii >= i0) & (jj >= j0) & (g.actnum[kk, jj, ii] > 0)))
            if mask is not None:
                self.assertTrue(np.all(mask[kk]))
            # Triangle's mean point lies in the original cell, not a compact filtered index.
            centres = v[t].mean(axis=1)
            self.assertTrue(np.all((centres[:, 0] >= g.xs[ii]) & (centres[:, 0] <= g.xs[ii + 1])))
            self.assertTrue(np.all((centres[:, 1] >= g.ys[jj]) & (centres[:, 1] <= g.ys[jj + 1])))
            self.assertTrue(np.all((centres[:, 2] >= 10 + kk * 10) & (centres[:, 2] <= 20 + kk * 10)))
        self.assertEqual(len(g.exterior_faces()), 3)
        self.assertEqual(len(g.exterior_faces(layer_mask=np.zeros(g.nk, bool), return_cell_ids=True)[3]), 0)

    def test_payload_and_validated_return(self):
        g, props = fixture()
        sc = Scene((0, 0))
        obj = sc.grid(g, "PERMX", 1, 1, props=props, layer_mask=[False, True, False])
        ids = decode(obj["cell_ids"], np.uint32)
        values = decode(obj["cell_values"], np.float64)
        np.testing.assert_array_equal(values, props["PERMX"].values.ravel()[ids])
        fs.COMPONENT_VALUES.clear()
        viewer3d(sc, "picktest", mesh=True)
        args = [p for k, p in fs.CALLS if k == "component:geomodel_viewer3d"][-1]
        self.assertTrue(args["mesh"])
        cell = int(ids[-1])
        fs.COMPONENT_VALUES["geomodel_viewer3d"] = dict(rev=args["rev"], object_id=obj["id"], cell_id=cell)
        result = viewer3d(sc, "picktest")
        kk, jj, ii = np.unravel_index(cell, g.actnum.shape)
        self.assertEqual((result["i"], result["j"], result["k"]), (ii + 1, jj + 1, kk + 1))
        self.assertEqual(result["value"], props["PERMX"].values.ravel()[cell])
        self.assertEqual(result["unit"], "mD")
        fs.COMPONENT_VALUES["geomodel_viewer3d"]["cell_id"] = 0
        self.assertIsNone(viewer3d(sc, "picktest"))
        fs.COMPONENT_VALUES.clear()
        props["PERMX"].values.ravel()[cell] = np.nan
        sc = Scene((0, 0))
        obj = sc.grid(g, "PERMX", props=props)
        self.assertTrue(np.isnan(decode(obj["cell_values"], np.float64)[decode(obj["cell_ids"], np.uint32) == cell]).all())
        viewer3d(sc, "undefinedtest")
        args = [p for k, p in fs.CALLS if k == "component:geomodel_viewer3d"][-1]
        fs.COMPONENT_VALUES["geomodel_viewer3d"] = dict(rev=args["rev"], object_id=obj["id"], cell_id=cell)
        self.assertIsNone(viewer3d(sc, "undefinedtest")["value"])
        fs.COMPONENT_VALUES["geomodel_viewer3d"]["rev"] = "outdated-scene"
        self.assertIsNone(viewer3d(sc, "undefinedtest"))
        fs.COMPONENT_VALUES.clear()

    def test_verified_webviz_tables_and_sparse_categories(self):
        g, _ = fixture()
        prop = SimpleNamespace(values=np.full(g.actnum.shape, .5), kind="continuous", unit="")
        self.assertEqual(grid_property(g, "SW", {"SW": prop})[0]["stops"], WEBVIZ_PHYSICS)
        self.assertEqual(grid_property(g, "PORO", {"PORO": prop})[0]["stops"], WEBVIZ_PHYSICS[::-1])
        prop.kind = "discrete"
        prop.values.flat[1] = 1000000
        prop.values.flat[0] = np.nan
        prop.values[np.isfinite(prop.values) & (prop.values < 1)] = -10
        spec, legend = grid_property(g, "FACIES", {"FACIES": prop})
        self.assertEqual(len(spec["colors"]), 2)
        self.assertEqual(spec["colors"][0], WEBVIZ_CATEGORIES[0])
        sc = Scene((0, 0))
        sc.grid(g, "FACIES", props={"FACIES": prop})

    def test_chrome_pointer_picking_filtered_and_unfiltered(self):
        if not os.environ.get("GEOMODEL_CHROME_TEST") and not os.environ.get("GEOMODEL_VIEWER_FIXTURE_ONLY"):
            self.skipTest("Set GEOMODEL_CHROME_TEST=1 to launch optional real Chrome test")
        chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        if not chrome.exists():
            self.skipTest("Chrome is unavailable")
        g, props = fixture()
        scenes = []
        for mask in (None, [False, True, False]):
            sc = Scene((0, 0))
            sc.grid(g, "PERMX", 1, 1, props=props, layer_mask=mask)
            scenes.append(sc.to_dict())
        host = ROOT / "components" / "_viewer_pick_test.html"
        profile = ROOT / "tests" / "_viewer_chrome_profile"
        source = """<!doctype html><iframe id="f" src="viewer3d/index.html" style="width:1100px;height:700px"></iframe>
<pre id="result">WAIT</pre><script>
const scenes=SCENES; const messages=[]; window.addEventListener('message',e=>messages.push(e.data));
function run(index){
 const w=document.getElementById('f').contentWindow;
 w.postMessage({type:'streamlit:render',args:{scene:scenes[index],rev:'r'+index,cam_key:'c'+index,height:700,ve:3,mesh:true}},'*');
 setTimeout(()=>{
 try{
 const v=w.__viewer; if(!v.init())throw Error('WebGL missing');
 v.setView(0,Math.PI/2-.001);v.render();
 const depth=index===0?10:20, point=v.project(50,30,depth);
 const canvas=w.document.getElementById('gl'),rect=canvas.getBoundingClientRect();
 const x=rect.left+point[0]/(canvas.width/rect.width),y=rect.top+point[1]/(canvas.height/rect.height);
 const main=w.document.getElementById('main');
 main.dispatchEvent(new w.PointerEvent('pointerdown',{clientX:x,clientY:y,button:0,pointerId:1,bubbles:true}));
 main.dispatchEvent(new w.PointerEvent('pointerup',{clientX:x,clientY:y,button:0,pointerId:1,bubbles:true}));
 const id=index===0?6:18, expected=index===0?106:118;
 setTimeout(()=>{
 const pick=messages.filter(m=>m.type==='streamlit:setComponentValue'&&m.value).at(-1)?.value;
 if(!pick||pick.cell_id!==id||pick.value!==expected||pick.i!==3||pick.j!==2||pick.k!==index+1)
   document.getElementById('result').textContent='FAIL '+JSON.stringify(pick);
 else if(index===0)run(1);else document.getElementById('result').textContent='PASS_PICKING';
 },100);
 }catch(e){document.getElementById('result').textContent='FAIL '+e.message;}
 },600);
}
setTimeout(()=>run(0),600);
</script>""".replace("SCENES", json.dumps(scenes))
        if os.environ.get("GEOMODEL_VIEWER_FIXTURE_ONLY"):
            host.write_text(source)
            self.skipTest(f"Browser fixture prepared at {host}")
        try:
            host.write_text(source)
            command = [str(chrome), "--headless=new", "--no-sandbox", "--allow-file-access-from-files",
                       "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
                       "--no-first-run", "--no-default-browser-check", "--disable-dev-shm-usage",
                       f"--user-data-dir={profile}", "--virtual-time-budget=5000", "--dump-dom", host.as_uri()]
            completed = subprocess.run(command, text=True, capture_output=True, timeout=40)
            self.assertIn('<pre id="result">PASS_PICKING</pre>', completed.stdout,
                          completed.stdout[-2500:] + completed.stderr[-1000:])
        finally:
            host.unlink(missing_ok=True)
            import shutil
            shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
