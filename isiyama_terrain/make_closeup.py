#!/usr/bin/env python3
"""石山公園周辺クローズアップ: 地形 + 建物/道路/鉄道/水域をオブジェクト別に出力(OBJ, mm単位)。

データ: 国土地理院 標高タイル(DEM5A) + 国土地理院ベクトルタイル(experimental_bvmap, ズーム16)
出力  : isiyama_closeup_mm.obj / .mtl / _objects.csv / _labels.csv / _preview.png
座標  : 原点=中心座標(CENTER)、X=東、Y=北、Z=上。1単位 = 1/UNIT_PER_M m (既定: 1単位=1mm)。
        標高は「最低地点(河床)=台座厚さ分」を基準にした相対値(実標高 = 出力Z/単位 + 基準標高 - BASE)。
注意  : 国土地理院データに建物の高さは無いため、建物は面積/種別による「仮定高さ」の押し出し(陸屋根)。
"""
import csv
import importlib.util
import math
import subprocess
import sys
from pathlib import Path

# ============================ 調整パラメータ ============================
CENTER_LAT = 34.6675          # 中心緯度
CENTER_LON = 133.9340         # 中心経度
SIZE_M = 600.0                # 範囲: 一辺[m]
Z_SCALE = 1.0                 # 高さ強調倍率(建築用途は1.0推奨)
TERRAIN_PITCH_M = 2.0         # 地形グリッドのピッチ[m]
BASE_THICKNESS_M = 5.0        # 地形ソリッドの台座厚[m]
UNIT_PER_M = 1000.0           # 出力単位: 1mあたりの単位数(1000 = mm)
WATER_DEPTH_M = 1.5           # 水域の仮定水深[m]
ROAD_THICKNESS_M = 0.5        # 道路スラブ厚[m]
ROAD_RAISE_M = 0.1            # 道路上面を地面から持ち上げる量[m]
MIN_BUILDING_AREA_M2 = 3.0    # これ未満の建物は除外
VT_ZOOM = 16                  # ベクトルタイルのズーム(最大16)
OUT_STEM = "isiyama_closeup_mm"
for _a in sys.argv[1:]:  # 例: --lat=34.66 --lon=133.93 --size=600 --out=name
    if _a.startswith("--lat="): CENTER_LAT = float(_a[6:])
    elif _a.startswith("--lon="): CENTER_LON = float(_a[6:])
    elif _a.startswith("--size="): SIZE_M = float(_a[7:])
    elif _a.startswith("--out="): OUT_STEM = _a[6:]
# 建物の仮定高さ[m] : (面積上限m2, 高さ)の表。 ftCode 3101=普通建物 3102=堅ろう建物 3111/3112=無壁舎
BUILDING_HEIGHTS = {
    3101: [(50, 3.5), (200, 6.5), (600, 9.0), (1e12, 12.0)],
    3102: [(100, 9.0), (400, 12.0), (1500, 18.0), (1e12, 25.0)],
    3111: [(1e12, 3.5)],
    3112: [(1e12, 3.5)],
}
# 道路幅員[m]: rnkWidth(0:~3m 1:3~5.5m 2:5.5~13m 3:13~19.5m 4:19.5m~)の代表値。Width属性があればそちらを優先
ROAD_WIDTHS = {0: 3.0, 1: 4.5, 2: 8.0, 3: 14.0, 4: 22.0}
ROAD_CENTERLINES = {2701: None, 2711: 2.0}   # ftCode: 幅員固定値(Noneならrnkで決定)
RAIL_CODES = {8201: 3.0, 2831: 3.0}           # ftCode: 幅員
# ======================================================================

REQUIRED = {"numpy": "numpy", "requests": "requests", "trimesh": "trimesh", "PIL": "pillow",
            "scipy": "scipy", "shapely": "shapely", "mapbox_vector_tile": "mapbox-vector-tile",
            "mapbox_earcut": "mapbox-earcut", "matplotlib": "matplotlib"}
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def ensure_deps():
    missing = [pkg for mod, pkg in REQUIRED.items() if importlib.util.find_spec(mod) is None]
    if missing:
        print("不足ライブラリをインストール:", missing)
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", *missing])


ensure_deps()
import numpy as np  # noqa: E402
import requests  # noqa: E402
import shapely  # noqa: E402
import trimesh  # noqa: E402
import mapbox_vector_tile as mvt  # noqa: E402
from scipy import ndimage  # noqa: E402
from scipy.interpolate import RegularGridInterpolator  # noqa: E402
from shapely.geometry import box, shape, Polygon, MultiPolygon, LineString, MultiLineString  # noqa: E402

import make_terrain as mt  # noqa: E402

mt.CENTER_LAT, mt.CENTER_LON = CENTER_LAT, CENTER_LON
R = mt.EARTH_R
HALF = SIZE_M / 2
CACHE = HERE / "tile_cache"
VT_URL = "https://cyberjapandata.gsi.go.jp/xyz/experimental_bvmap/{z}/{x}/{y}.pbf"
LOCAL_BOX = box(-HALF, -HALF, HALF, HALF)
TILE_BOX = box(0, 0, 4096, 4096)


# ---------------------------------------------------------------- 座標変換
def tile_to_local(tx, ty, cx, cy, z):
    n = 256 * 2 ** z
    px = (tx + np.asarray(cx) / 4096.0) * 256
    py = (ty + np.asarray(cy) / 4096.0) * 256
    lon = px / n * 360 - 180
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * py / n))))
    e = np.radians(lon - CENTER_LON) * R * math.cos(math.radians(CENTER_LAT))
    nn = np.radians(lat - CENTER_LAT) * R
    return e, nn


def geoms_of(g, kind):
    if g.is_empty:
        return []
    if g.geom_type == kind:
        return [g]
    if hasattr(g, "geoms"):
        return [p for sub in g.geoms for p in geoms_of(sub, kind)]
    return []


# ---------------------------------------------------------------- ベクトルタイル取得
def fetch_vector_tiles():
    corners_lon = [CENTER_LON + math.degrees(s * HALF / (R * math.cos(math.radians(CENTER_LAT)))) for s in (-1, 1)]
    corners_lat = [CENTER_LAT + math.degrees(s * HALF / R) for s in (-1, 1)]
    px, py = mt.lonlat_to_pixel(np.array(corners_lon), np.array(corners_lat), VT_ZOOM)
    tx0, tx1 = int(px.min() // 256), int(px.max() // 256)
    ty0, ty1 = int(py.min() // 256), int(py.max() // 256)
    CACHE.mkdir(exist_ok=True)
    tiles = {}
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            f = CACHE / f"vt_{VT_ZOOM}_{tx}_{ty}.pbf"
            if not f.exists():
                r = requests.get(VT_URL.format(z=VT_ZOOM, x=tx, y=ty), timeout=60)
                if r.status_code != 200:
                    print(f"  タイル {tx}/{ty} 取得不可 (HTTP {r.status_code})")
                    continue
                f.write_bytes(r.content)
            tiles[(tx, ty)] = mvt.decode(f.read_bytes(), default_options={"y_coord_down": True})
    print(f"ベクトルタイル: {len(tiles)}枚 (z={VT_ZOOM})")
    return tiles


def collect(tiles):
    """レイヤ別に、ローカルm座標のshapely図形(範囲でクリップ済み)を返す。"""
    out = {"building": [], "building_edge": [], "water": [], "line": [], "label": []}
    for (tx, ty), d in tiles.items():
        def tf(g):
            return shapely.transform(g, lambda c: np.column_stack(tile_to_local(tx, ty, c[:, 0], c[:, 1], VT_ZOOM)))
        for ftr in d.get("building", {}).get("features", []):
            if ftr["geometry"]["type"] not in ("Polygon", "MultiPolygon"):
                continue
            g = shape(ftr["geometry"])
            g = g if g.is_valid else shapely.make_valid(g)
            g = g.intersection(TILE_BOX)
            for p in geoms_of(g, "Polygon"):
                edge = p.bounds[0] <= 0.5 or p.bounds[1] <= 0.5 or p.bounds[2] >= 4095.5 or p.bounds[3] >= 4095.5
                out["building_edge" if edge else "building"].append((ftr["properties"]["ftCode"], tf(p)))
        for ftr in d.get("waterarea", {}).get("features", []):
            g = shape(ftr["geometry"])
            g = (g if g.is_valid else shapely.make_valid(g)).intersection(TILE_BOX)
            out["water"] += [tf(p) for p in geoms_of(g, "Polygon")]
        for layer in ("road", "railway"):
            for ftr in d.get(layer, {}).get("features", []):
                if ftr["geometry"]["type"] not in ("LineString", "MultiLineString"):
                    continue
                g = shape(ftr["geometry"]).intersection(TILE_BOX)
                for ln in geoms_of(g, "LineString"):
                    for seg in geoms_of(tf(ln).intersection(LOCAL_BOX), "LineString"):
                        out["line"].append((layer, ftr["properties"], seg))
        for ftr in d.get("label", {}).get("features", []):
            if ftr["geometry"]["type"] == "Point" and ftr["properties"].get("knj"):
                x, y = ftr["geometry"]["coordinates"]
                e, n = tile_to_local(tx, ty, x, y, VT_ZOOM)
                if abs(e) <= HALF and abs(n) <= HALF:
                    out["label"].append((ftr["properties"]["knj"], float(e), float(n)))
    # タイル境界で分割された建物を結合(境界に接する断片のみ)
    merged = []
    by_code = {}
    for code, p in out["building_edge"]:
        by_code.setdefault(code, []).append(p)
    for code, ps in by_code.items():
        u = shapely.unary_union([p.buffer(0.02) for p in ps]).buffer(-0.02)
        merged += [(code, q) for q in geoms_of(u, "Polygon")]
    bld = []
    for code, p in out["building"] + merged:
        for q in geoms_of(p.intersection(LOCAL_BOX), "Polygon"):
            if q.area >= MIN_BUILDING_AREA_M2:
                bld.append((code, q))
    out["building"] = bld
    out["water"] = [q for q in geoms_of(shapely.unary_union([p.buffer(0.02) for p in out["water"]]).buffer(-0.02)
                                        .intersection(LOCAL_BOX), "Polygon") if q.area > 20]
    return out


# ---------------------------------------------------------------- 地形
def build_terrain(water_polys):
    n = int(round(SIZE_M / TERRAIN_PITCH_M)) + 1
    xs, ys, raw = mt.build_dem(HALF, n, n, TERRAIN_PITCH_M, fill=False)
    X, Y = np.meshgrid(xs, ys)
    h = raw.copy()
    valid_any = ~np.isnan(raw)
    gmin = np.nanmin(raw)
    levels = []
    water_mask = np.zeros_like(raw, bool)
    for p in water_polys:
        m = shapely.contains_xy(p, X, Y)
        vals = raw[m & valid_any]
        if len(vals) >= 5:
            lv = float(np.median(vals))
        else:
            near = shapely.contains_xy(p.buffer(30), X, Y) & valid_any & ~m
            lv = float(np.median(raw[near])) - 0.3 if near.any() else float(gmin)
        levels.append(lv)
        water_mask |= m
    # 無効値は最近傍で補完 → 水域は河床まで掘り下げ
    idx = ndimage.distance_transform_edt(np.isnan(h), return_distances=False, return_indices=True)
    h = h[tuple(idx)]
    deck = h.copy()
    for p, lv in zip(water_polys, levels):
        m = shapely.contains_xy(p, X, Y)
        h[m] = lv - WATER_DEPTH_M
        deck[m] = lv
    return xs, ys, h, deck, levels, raw


def make_interp(xs, ys, grid):
    f = RegularGridInterpolator((ys, xs), grid, bounds_error=False, fill_value=None)
    return lambda x, y: f(np.column_stack([np.asarray(y), np.asarray(x)]))


# ---------------------------------------------------------------- ソリッド生成
def prism(poly, bottom_fn, top_fn):
    """多角形を押し出して、頂点ごとにZを与える(水密ソリッド)。"""
    m = trimesh.creation.extrude_polygon(poly, 1.0, engine="earcut")
    v = m.vertices.copy()
    top = v[:, 2] > 0.5
    v[top, 2] = top_fn(v[top, 0], v[top, 1])
    v[~top, 2] = bottom_fn(v[~top, 0], v[~top, 1])
    out = trimesh.Trimesh(v, m.faces, process=True)
    if not out.is_watertight:
        trimesh.repair.fill_holes(out)
    return out


def building_height(code, area):
    for amax, hgt in BUILDING_HEIGHTS.get(code, BUILDING_HEIGHTS[3101]):
        if area < amax:
            return hgt


def ribbon(line, width):
    p = line.buffer(width / 2, cap_style="flat", join_style="round", quad_segs=3)
    p = p.intersection(LOCAL_BOX)
    return [shapely.segmentize(q, 8.0) for q in geoms_of(p, "Polygon") if q.area > 0.5]


# ---------------------------------------------------------------- 出力
MATERIALS = {
    "Terrain": (0.55, 0.60, 0.40), "Water": (0.25, 0.50, 0.80), "Road": (0.45, 0.45, 0.47),
    "Rail": (0.25, 0.22, 0.20), "Building_Normal": (0.85, 0.80, 0.70),
    "Building_Solid": (0.75, 0.75, 0.80), "Building_Shed": (0.80, 0.70, 0.55),
}


def write_obj(objs, stem):
    with open(HERE / f"{stem}.mtl", "w") as f:
        for name, kd in MATERIALS.items():
            f.write(f"newmtl {name}\nKd {kd[0]} {kd[1]} {kd[2]}\nKa 0 0 0\nKs 0 0 0\nd 1\n\n")
    off = 0
    with open(HERE / f"{stem}.obj", "w") as f:
        f.write(f"# units: 1 = {1000 / UNIT_PER_M:g} mm\nmtllib {stem}.mtl\n")
        for name, cat, mesh in objs:
            f.write(f"o {name}\nusemtl {cat}\n")
            np.savetxt(f, mesh.vertices * UNIT_PER_M, fmt="v %.2f %.2f %.2f")
            np.savetxt(f, mesh.faces + 1 + off, fmt="f %d %d %d")
            off += len(mesh.vertices)


def write_dae(objs, stem):
    """SketchUp(.skpの代替)に直接読み込めるCollada(.dae)。座標はmm、unit=0.001mで実寸。"""
    import collada
    mesh = collada.Collada()
    mesh.assetInfo.unitname, mesh.assetInfo.unitmeter = "millimeter", 1.0 / UNIT_PER_M
    mesh.assetInfo.upaxis = collada.asset.UP_AXIS.Z_UP
    mats = {}
    for cat, kd in MATERIALS.items():
        eff = collada.material.Effect(f"{cat}_fx", [], "lambert", diffuse=(*kd, 1.0), double_sided=True)
        mat = collada.material.Material(f"{cat}_mat", cat, eff)
        mesh.effects.append(eff); mesh.materials.append(mat); mats[cat] = mat
    nodes = []
    for name, cat, m in objs:
        v = (m.vertices * UNIT_PER_M).astype(np.float32)
        src = collada.source.FloatSource(f"{name}-v", v.ravel(), ("X", "Y", "Z"))
        geom = collada.geometry.Geometry(mesh, f"{name}-g", name, [src])
        ils = collada.source.InputList()
        ils.addInput(0, "VERTEX", f"#{name}-v")
        geom.primitives.append(geom.createTriangleSet(m.faces.astype(np.int32).ravel(), ils, f"{cat}_mat"))
        mesh.geometries.append(geom)
        nodes.append(collada.scene.Node(name, children=[collada.scene.GeometryNode(geom, [collada.scene.MaterialNode(f"{cat}_mat", mats[cat], inputs=[])])]))
    mesh.scenes.append(collada.scene.Scene("scene", nodes))
    mesh.scene = mesh.scenes[0]
    mesh.write(str(HERE / f"{stem}.dae"))


def write_dxf(objs, stem):
    """AutoCAD DXF(3Dポリフェースメッシュ、種別ごとにレイヤ分け、単位mm)。"""
    import ezdxf
    doc = ezdxf.new("R2010", setup=True)
    doc.units = ezdxf.units.MM
    for i, (cat, kd) in enumerate(MATERIALS.items()):
        doc.layers.add(cat, true_color=ezdxf.colors.rgb2int(tuple(int(c * 255) for c in kd)))
    msp = doc.modelspace()
    for name, cat, m in objs:
        v = m.vertices * UNIT_PER_M
        pf = msp.add_polyface(dxfattribs={"layer": cat})
        pf.append_faces([[tuple(v[i]) for i in f] for f in m.faces], dxfattribs={"layer": cat})
        pf.dxf.handle  # noqa: B018
    doc.saveas(str(HERE / f"{stem}.dxf"))


def write_ifc(objs, stem, rows):
    """IFC4(三角形分割ジオメトリ、単位mm)。地形=IfcGeographicElement、その他=IfcBuildingElementProxy。"""
    import ifcopenshell
    import ifcopenshell.api as api
    f = api.run("project.create_file", version="IFC4")
    proj = api.run("root.create_entity", f, ifc_class="IfcProject", name="Isiyama close-up")
    api.run("unit.assign_unit", f, length={"is_metric": True, "raw": "MILLIMETERS"})
    ctx = api.run("context.add_context", f, context_type="Model")
    body = api.run("context.add_context", f, context_type="Model", context_identifier="Body",
                   target_view="MODEL_VIEW", parent=ctx)
    site = api.run("root.create_entity", f, ifc_class="IfcSite", name="Site")
    api.run("aggregate.assign_object", f, products=[site], relating_object=proj)
    styles = {}
    for cat, kd in MATERIALS.items():
        st = api.run("style.add_style", f, name=cat)
        api.run("style.add_surface_style", f, style=st, ifc_class="IfcSurfaceStyleShading",
                attributes={"SurfaceColour": {"Name": None, "Red": kd[0], "Green": kd[1], "Blue": kd[2]}})
        styles[cat] = st
    info = {r[0]: r for r in rows}
    prods = []
    for name, cat, m in objs:
        if cat == "Terrain":
            p = api.run("root.create_entity", f, ifc_class="IfcGeographicElement", name=name, predefined_type="TERRAIN")
        else:
            p = api.run("root.create_entity", f, ifc_class="IfcBuildingElementProxy", name=name)
            p.ObjectType = cat
        v = (m.vertices * UNIT_PER_M).astype(float)
        pts = f.createIfcCartesianPointList3D([tuple(map(float, x)) for x in v])
        fs = f.createIfcTriangulatedFaceSet(pts, None, None, [tuple(int(i) + 1 for i in t) for t in m.faces])
        rep = f.createIfcShapeRepresentation(body, "Body", "Tessellation", [fs])
        p.Representation = f.createIfcProductDefinitionShape(None, None, [rep])
        api.run("geometry.edit_object_placement", f, product=p)
        api.run("style.assign_item_style", f, item=fs, style=styles[cat])
        if name in info and info[name][4]:
            ps = api.run("pset.add_pset", f, product=p, name="Isiyama_Source")
            api.run("pset.edit_pset", f, pset=ps, properties={"Category": cat, "Note": info[name][4]})
        prods.append(p)
    api.run("spatial.assign_container", f, products=prods, relating_structure=site)
    f.write(str(HERE / f"{stem}.ifc"))


def main():
    print(f"中心 ({CENTER_LAT}, {CENTER_LON}) / 範囲 {SIZE_M:g}m角 / 単位 1={1000 / UNIT_PER_M:g}mm")
    feats = collect(fetch_vector_tiles())
    print(f"建物 {len(feats['building'])} / 水域 {len(feats['water'])} / 道路・鉄道線 {len(feats['line'])}")
    xs, ys, h, deck, levels, raw = build_terrain(feats["water"])
    zmin = float(h.min())
    zt = lambda a: (a - zmin) * Z_SCALE + BASE_THICKNESS_M  # 実標高 → モデルZ[m]
    ground = make_interp(xs, ys, zt(h))
    deckf = make_interp(xs, ys, zt(deck))

    objs, rows = [], []
    terr, _ = mt.build_solid(xs, ys, h, Z_SCALE, BASE_THICKNESS_M, 1.0)
    objs.append(("Terrain", "Terrain", terr))
    rows.append(["Terrain", "Terrain", "", "", ""])

    for i, (p, lv) in enumerate(zip(feats["water"], levels), 1):
        z0, z1 = zt(lv - WATER_DEPTH_M), zt(lv)
        m = prism(p, lambda x, y, z0=z0: np.full(len(x), z0), lambda x, y, z1=z1: np.full(len(x), z1))
        objs.append((f"Water_{i:02d}", "Water", m))
        rows.append([f"Water_{i:02d}", "Water", f"{p.area:.1f}", f"{WATER_DEPTH_M:.1f}", f"水面標高 {lv:.2f}m"])

    bad = 0
    for i, (code, p) in enumerate(sorted(feats["building"], key=lambda t: (t[0], -t[1].area)), 1):
        hgt = building_height(code, p.area) * Z_SCALE
        sample = np.array(p.exterior.coords)
        gmax = float(ground(sample[:, 0], sample[:, 1]).max())
        try:
            m = prism(p, lambda x, y: ground(x, y) - 0.5, lambda x, y, t=gmax + hgt: np.full(len(x), t))
        except Exception:
            bad += 1
            continue
        cat = {3102: "Building_Solid", 3101: "Building_Normal"}.get(code, "Building_Shed")
        name = f"Bldg_{i:04d}"
        objs.append((name, cat, m))
        rows.append([name, cat, f"{p.area:.1f}", f"{hgt:.1f}", f"ftCode {code} 高さは仮定"])
    if bad:
        print(f"  三角形分割に失敗し除外した建物: {bad}")

    k = {"road": 0, "railway": 0}
    for layer, props, ln in feats["line"]:
        code = props.get("ftCode")
        if layer == "road":
            if code not in ROAD_CENTERLINES:
                continue
            w = props.get("Width") or ROAD_CENTERLINES[code] or ROAD_WIDTHS.get(props.get("rnkWidth", 1), 4.5)
            cat, pre = "Road", "Road"
        else:
            if code not in RAIL_CODES:
                continue
            w, cat, pre = RAIL_CODES[code], "Rail", "Rail"
        for q in ribbon(ln, float(w)):
            try:
                m = prism(q, lambda x, y: deckf(x, y) + ROAD_RAISE_M - ROAD_THICKNESS_M, lambda x, y: deckf(x, y) + ROAD_RAISE_M)
            except Exception:
                continue
            k[layer] += 1
            name = f"{pre}_{k[layer]:04d}"
            objs.append((name, cat, m))
            rows.append([name, cat, f"{q.area:.1f}", f"{ROAD_THICKNESS_M}", f"幅員 {w}m"])

    nw = [name for name, _, m in objs if not (m.is_watertight and m.volume > 0)]
    write_obj(objs, OUT_STEM)
    write_dae(objs, OUT_STEM)
    write_dxf(objs, OUT_STEM)
    write_ifc(objs, OUT_STEM, rows)
    with open(HERE / f"{OUT_STEM}_objects.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["name", "category", "area_m2", "height_or_thickness_m", "note"])
        w.writerows(rows)
    with open(HERE / f"{OUT_STEM}_labels.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["name", "x_mm", "y_mm"])
        w.writerows([[n, round(e * 1000), round(nn * 1000)] for n, e, nn in feats["label"]])
    make_preview(feats, xs, ys, h)

    allv = np.vstack([m.vertices for _, _, m in objs]) * UNIT_PER_M
    ext = allv.max(0) - allv.min(0)
    cnt = {}
    for _, c, _ in objs:
        cnt[c] = cnt.get(c, 0) + 1
    print("---------------- 結果 ----------------")
    print(f"オブジェクト数: {len(objs)}  内訳: {cnt}")
    print(f"総頂点数: {len(allv):,} / 総三角形数: {sum(len(m.faces) for _, _, m in objs):,}")
    print(f"全体サイズ(出力単位={1000 / UNIT_PER_M:g}mm): {ext[0]:,.0f} x {ext[1]:,.0f} x {ext[2]:,.0f}")
    print(f"実標高: 河床/最低 {zmin:.2f}m, 最高 {h.max():.2f}m (地形Z基準=台座{BASE_THICKNESS_M}m)")
    print(f"水密でないオブジェクト: {len(nw)}" + (f" 例: {nw[:5]}" if nw else ""))
    print("出力:", HERE / f"{OUT_STEM}.obj")


def make_preview(feats, xs, ys, h):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource
    fig, ax = plt.subplots(figsize=(10, 10))
    ls = LightSource(315, 40)
    ax.imshow(ls.shade(h, plt.cm.Greens, vert_exag=2, blend_mode="soft"), origin="lower",
              extent=[xs[0], xs[-1], ys[0], ys[-1]])
    for p in feats["water"]:
        ax.fill(*p.exterior.xy, color="#4a90d9", alpha=0.8)
    for layer, props, ln in feats["line"]:
        code = props.get("ftCode")
        if (layer == "road" and code in ROAD_CENTERLINES) or (layer == "railway" and code in RAIL_CODES):
            ax.plot(*ln.xy, color="#555", lw=1.2)
    for code, p in feats["building"]:
        ax.fill(*p.exterior.xy, color="#d9a066", ec="#7a4a1a", lw=0.3)
    ax.set_aspect("equal")
    ax.set_title(f"{SIZE_M:g}m square (m from center)")
    fig.tight_layout()
    fig.savefig(HERE / f"{OUT_STEM}_preview.png", dpi=100)


if __name__ == "__main__":
    main()
