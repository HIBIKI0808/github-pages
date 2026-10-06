#!/usr/bin/env python3
"""石山公園周辺（岡山市北区）の3D地形モデル生成スクリプト。

国土地理院 標高タイル(DEM5A / DEM10B, PNG形式)を取得 → 標高配列化 →
底面・側面を閉じた水密メッシュ(STL/OBJ)を出力する。

使い方:  python make_terrain.py            # 実データ(要: cyberjapandata.gsi.go.jp への接続)
         python make_terrain.py --synthetic  # 接続不可環境でのパイプライン検証用(ダミー地形)
"""
import importlib.util
import math
import subprocess
import sys
from pathlib import Path

# ============================ 調整パラメータ ============================
CENTER_LAT = 34.6675          # 中心緯度
CENTER_LON = 133.9340         # 中心経度
SIZE_KM = 3.5                 # 範囲サイズ: 一辺の長さ[km]（中心から東西南北に各 SIZE_KM/2）
Z_SCALE = 1.3                 # 高さ強調倍率（1.0〜1.5推奨）
GRID_PITCH_M = 5.0            # サンプリングピッチ[m]（小さいほど高精細・重い）
ZOOM = 15                     # 標高タイルのズームレベル(15=DEM5A, 14=DEM10B)
BASE_THICKNESS_M = 20.0       # 最低標高点の下に付ける台座の厚み[m]（Z強調前）
UNIT_PER_M = 1.0              # 出力単位: 1mあたりの単位数(1.0=メートル, 1000=mm)
OUT_STEM = "isiyama_park_terrain"
# ======================================================================

REQUIRED = {"numpy": "numpy", "requests": "requests", "trimesh": "trimesh", "PIL": "pillow"}
HERE = Path(__file__).resolve().parent
CACHE = HERE / "tile_cache"
TILE_URLS = [  # 優先順に試行(DEM5A → DEM10B)
    "https://cyberjapandata.gsi.go.jp/xyz/dem5a_png/{z}/{x}/{y}.png",
    "https://cyberjapandata.gsi.go.jp/xyz/dem_png/{z}/{x}/{y}.png",
]


def ensure_deps():
    missing = [pkg for mod, pkg in REQUIRED.items() if importlib.util.find_spec(mod) is None]
    if missing:
        print("不足ライブラリをインストール:", missing)
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", *missing])


ensure_deps()
import numpy as np  # noqa: E402
import requests  # noqa: E402
import trimesh  # noqa: E402
from PIL import Image  # noqa: E402
import io  # noqa: E402

EARTH_R = 6378137.0


def lonlat_to_pixel(lon, lat, z):
    n = 256 * 2 ** z
    x = (np.asarray(lon) + 180.0) / 360.0 * n
    s = np.sin(np.radians(lat))
    y = (0.5 - np.log((1 + s) / (1 - s)) / (4 * np.pi)) * n
    return x, y


def fetch_tile(z, x, y):
    """標高[m]の256x256配列。取得不可はNaN。"""
    CACHE.mkdir(exist_ok=True)
    for k, url in enumerate(TILE_URLS):
        f = CACHE / f"{k}_{z}_{x}_{y}.png"
        if not f.exists():
            for attempt in range(3):
                try:
                    r = requests.get(url.format(z=z, x=x, y=y), timeout=30)
                except requests.RequestException:
                    continue
                if r.status_code == 200:
                    f.write_bytes(r.content)
                    break
                if r.status_code == 404:
                    break
        if f.exists():
            rgb = np.asarray(Image.open(f).convert("RGB"), dtype=np.int64)
            v = rgb[..., 0] * 65536 + rgb[..., 1] * 256 + rgb[..., 2]
            h = np.where(v < 2 ** 23, v, v - 2 ** 24) * 0.01
            h[v == 2 ** 23] = np.nan  # 無効値
            return h
    return np.full((256, 256), np.nan)


def build_dem(half_m, nx, ny, pitch, fill=True):
    """中心からの局地メートル座標グリッド上の標高(ny,nx)を返す。行0=南端。"""
    xs = (np.arange(nx) - (nx - 1) / 2) * pitch
    ys = (np.arange(ny) - (ny - 1) / 2) * pitch
    dlat = np.degrees(ys / EARTH_R)
    dlon = np.degrees(xs / (EARTH_R * math.cos(math.radians(CENTER_LAT))))
    LON, LAT = np.meshgrid(CENTER_LON + dlon, CENTER_LAT + dlat)
    px, py = lonlat_to_pixel(LON, LAT, ZOOM)
    tx0, tx1 = int(px.min() // 256), int(px.max() // 256)
    ty0, ty1 = int(py.min() // 256), int(py.max() // 256)
    print(f"タイル取得: z={ZOOM} x={tx0}-{tx1} y={ty0}-{ty1} ({(tx1-tx0+1)*(ty1-ty0+1)}枚)")
    mos = np.full(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256), np.nan)
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            mos[(ty - ty0) * 256:(ty - ty0 + 1) * 256, (tx - tx0) * 256:(tx - tx0 + 1) * 256] = fetch_tile(ZOOM, tx, ty)
    if np.isnan(mos).all():
        sys.exit("標高タイルを1枚も取得できませんでした(ネットワーク/ホスト許可を確認)。")
    # バイリニア補間(画素中心基準)
    u = px - tx0 * 256 - 0.5
    v = py - ty0 * 256 - 0.5
    i0 = np.clip(np.floor(u).astype(int), 0, mos.shape[1] - 2)
    j0 = np.clip(np.floor(v).astype(int), 0, mos.shape[0] - 2)
    fu = np.clip(u - i0, 0, 1)
    fv = np.clip(v - j0, 0, 1)
    h = (mos[j0, i0] * (1 - fu) * (1 - fv) + mos[j0, i0 + 1] * fu * (1 - fv)
         + mos[j0 + 1, i0] * (1 - fu) * fv + mos[j0 + 1, i0 + 1] * fu * fv)
    nan_ratio = np.isnan(h).mean()
    if fill and nan_ratio:
        print(f"無効値(水域/欠測)の割合: {nan_ratio:.1%} → 範囲内の最低標高で補完")
        h = np.where(np.isnan(h), np.nanmin(h), h)
    return xs, ys, h


def synthetic_dem(nx, ny, pitch):
    """検証用ダミー地形(実データではない)。"""
    xs = (np.arange(nx) - (nx - 1) / 2) * pitch
    ys = (np.arange(ny) - (ny - 1) / 2) * pitch
    X, Y = np.meshgrid(xs, ys)
    h = 3 + 60 * np.exp(-(((X - 1200) / 500) ** 2 + ((Y - 300) / 400) ** 2)) + 2 * np.sin(X / 150)
    return xs, ys, h


def build_solid(xs, ys, h, z_scale, base_m, unit):
    """上面グリッド + 底面(ファン) + 側面で閉じた水密メッシュ。"""
    ny, nx = h.shape
    zmin = float(h.min())
    top_z = ((h - zmin) * z_scale + base_m) * unit
    X, Y = np.meshgrid(xs * unit, ys * unit)
    top = np.column_stack([X.ravel(), Y.ravel(), top_z.ravel()])
    idx = np.arange(nx * ny).reshape(ny, nx)
    # 上面(法線+Z)
    a, b, c, d = idx[:-1, :-1], idx[:-1, 1:], idx[1:, 1:], idx[1:, :-1]
    faces = [np.column_stack([a.ravel(), b.ravel(), c.ravel()]),
             np.column_stack([a.ravel(), c.ravel(), d.ravel()])]
    # 外周(上から見て反時計回り)
    ring = ([(i, 0) for i in range(nx - 1)] + [(nx - 1, j) for j in range(ny - 1)]
            + [(i, ny - 1) for i in range(nx - 1, 0, -1)] + [(0, j) for j in range(ny - 1, 0, -1)])
    ring_top = np.array([idx[j, i] for i, j in ring])
    m = len(ring)
    base0 = len(top)
    bottom = np.column_stack([top[ring_top, 0], top[ring_top, 1], np.zeros(m)])
    center = np.array([[0.0, 0.0, 0.0]])
    cidx = base0 + m
    k = np.arange(m)
    k2 = (k + 1) % m
    bk, bk2 = base0 + k, base0 + k2
    faces.append(np.column_stack([bk, bk2, ring_top[k2]]))        # 側面
    faces.append(np.column_stack([bk, ring_top[k2], ring_top[k]]))
    faces.append(np.column_stack([np.full(m, cidx), bk2, bk]))    # 底面(法線-Z)
    mesh = trimesh.Trimesh(np.vstack([top, bottom, center]), np.vstack(faces), process=False)
    return mesh, zmin


def main():
    synthetic = "--synthetic" in sys.argv
    n = int(round(SIZE_KM * 1000 / GRID_PITCH_M)) + 1
    print(f"中心 ({CENTER_LAT}, {CENTER_LON}) / 範囲 {SIZE_KM}km角 / ピッチ {GRID_PITCH_M}m / グリッド {n}x{n}")
    xs, ys, h = synthetic_dem(n, n, GRID_PITCH_M) if synthetic else build_dem(SIZE_KM * 500, n, n, GRID_PITCH_M)
    mesh, zmin = build_solid(xs, ys, h, Z_SCALE, BASE_THICKNESS_M, UNIT_PER_M)
    if not mesh.is_winding_consistent or mesh.volume < 0:
        trimesh.repair.fix_normals(mesh)
    stem = OUT_STEM + ("_SYNTHETIC" if synthetic else "")
    for ext in ("stl", "obj"):
        mesh.export(HERE / f"{stem}.{ext}")
    ext_m = mesh.extents / UNIT_PER_M
    print("---------------- 結果 ----------------")
    print(f"標高範囲(実測): {h.min():.2f} 〜 {h.max():.2f} m  (Z_SCALE={Z_SCALE})")
    print(f"頂点数: {len(mesh.vertices):,} / 三角形数: {len(mesh.faces):,}")
    print(f"実寸換算サイズ: 東西 {ext_m[0]:.1f} m × 南北 {ext_m[1]:.1f} m × 高さ {ext_m[2]:.1f} m (台座{BASE_THICKNESS_M}m込み・Z強調後)")
    print(f"モデルサイズ(出力単位): {mesh.extents[0]:.1f} x {mesh.extents[1]:.1f} x {mesh.extents[2]:.1f}")
    print(f"水密: {mesh.is_watertight} / 法線整合: {mesh.is_winding_consistent} / 体積: {mesh.volume:,.0f}")
    print("出力:", HERE / f"{stem}.stl", HERE / f"{stem}.obj")


if __name__ == "__main__":
    main()
