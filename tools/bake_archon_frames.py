from __future__ import annotations

"""Bake Warframe Archon (Kahl) MOD frame chrome into static browser PNGs.

The in-game Archon frame is drawn by FlashProcedurals shaders, so no static
textures exist for it. An earlier revision approximated the shader lighting
offline; the result looked flat and missed the rarity ornament entirely.
The game's own UI renders, however, are published as full-card images
(wiki.warframe.com hosts them as <ModName>Mod.png). All five Archon warframe
mods share identical frame chrome, so a per-pixel consensus mask across the
five cards isolates the static frame (top bar + winged-diamond ornament,
full-height side rails, bottom bar, lower tab) from the varying artwork and
text. The extracted layers are game-pixel-true; no lighting approximation
remains for the frame itself. Flat tinted layers (background, rank pips,
drain backer) still derive from the companion-app Legendary assets.
"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tools" / "archon_frame_source"
CARDS = SOURCE / "wiki_cards"
OUTPUT = ROOT / "frontend" / "assets" / "mods" / "frame"

CARD_NAMES = ["ArchonContinuity", "ArchonFlow", "ArchonIntensify", "ArchonStretch", "ArchonVitality"]
CONSENSUS_TOLERANCE = 8

# Card-space geometry measured on the 254x373 full-card render.
TOP_BAND = (0, 0, 254, 34)  # top bar + winged diamond + five small diamonds + upper leg tips
BOTTOM_BAND = (0, 296, 254, 373)  # lower legs, tab window, bottom bar, pip strip
TAB_RECT = (24, 302, 230, 334)  # compat tab incl. gold border (cut out of the band)
TAB_TEXT_RECT = (73, 308, 183, 330)  # card-space rect holding the "WARFRAME" text only
TAB_FILL_SAMPLE = (53, 68)  # card-space x range of clean tab interior used as fill source
PIP_ZONE = (45, 349, 210, 365)  # rank pip row sitting under the bottom bar
RAIL_LEFT = (0, 0, 15, 373)  # 顶部腿脚过渡段宽达 x14，窄裁会截断斜切装饰
RAIL_RIGHT = (239, 0, 254, 373)
# 中段侧栏：顶/底框之间的纯橙色边框。共识可信行锚点 + 逐列垂直插值——朴素
# 中位数会把各卡立绘差异拌进半透明边框，渲染成马赛克斑块；边框本身纵向平滑，
# 插值无失真。行范围裁掉两端：y34-82 有顶框腿脚/翼饰侵入、y278-296 有底框腿
# 脚（它们已由顶/底框素材自身提供，折叠态 262 行压成 22px 时会糊成色块），
# 只取中间的纯边框段，CSS object-fit:fill 拉伸后与两框重叠约 1px 闭合。
# 显示宽度仅 11px。
RAIL_MID_TOP = 90
RAIL_MID_BOTTOM = 278
# 底框暗板区（卡牌空间 y296-349）：游戏里是一整块半透明暗板，共识只能留住
# 碰巧相似的像素，渲染成不均匀的黑色斑块。改为只保留暖色金属（腿脚/饰条），
# 暗板交给应用自身的深色底。PIP 行用行内深色像素的中位色均匀填充（抹掉点子，
# 应用自绘等级点）。
BOTTOM_PLATE_END = 349


def _load_cards() -> tuple[list, object]:
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - managed runtime ships numpy
        raise SystemExit("numpy is required for the consensus extraction") from exc
    cards = []
    for name in CARD_NAMES:
        path = CARDS / f"wiki_{name}Mod.png"
        if not path.exists():
            raise SystemExit(f"missing consensus card render: {path}")
        cards.append(np.asarray(Image.open(path).convert("RGBA"), dtype=np.int16))
    shape = cards[0].shape
    if any(card.shape != shape for card in cards):
        raise SystemExit("consensus card renders must share dimensions")
    return cards, np


def _consensus_mask(cards, np):
    stack = np.stack(cards)
    spread = stack.max(axis=0) - stack.min(axis=0)
    return (spread[..., :3].max(axis=-1) <= CONSENSUS_TOLERANCE) & (spread[..., 3] <= CONSENSUS_TOLERANCE)


def _band(cards, mask, np, box, static_only=True):
    x0, y0, x1, y1 = box
    band = cards[0][y0:y1, x0:x1].copy()
    if static_only:
        band[~mask[y0:y1, x0:x1]] = 0
    return band


def _strip_dark_edges(band, np):
    """Erase the wiki render's anti-aliased black edge hugging the card body.

    The full-card renders carry a near-black soft edge (rgb ~ 0, alpha 38-222)
    just outside the opaque card body. It is identical on all five cards, so
    consensus keeps it and it paints a faint black ring around the card on the
    app's dark UI. Opaque dark chrome grooves (alpha 255) are real frame and
    must be kept.
    """
    dark = (band[..., :3].max(axis=-1) <= 12) & (band[..., 3] < 250)
    band[dark] = 0


def _erase_cool_haze(band, np, from_row, offset_y):
    """Drop cool-toned pixels below the chrome (art haze the consensus kept).

    Real frame pixels below the top chrome (leg tips, gold trim lines, dark
    grooves) are all warm (r > b); the semi-transparent haze over the artwork
    is cool/neutral. Only rows at/below ``from_row`` (card space) are touched.
    """
    region = band[from_row - offset_y :]
    cool = region[..., 0] - region[..., 2] <= 0
    region[cool] = 0


def _flatten_plate(band, np, to_row, offset_y, color=(26, 25, 22, 255)):
    """Flatten the bottom band's dark-plate rows to a uniform opaque panel.

    The in-game dark plate behind the tab is a translucent panel; per-card art
    behind it differs, so consensus leaves a patchy black mess, and a plain
    erasure lets slot labels beneath the expanded card bleed through. Fill the
    plate (card-body columns only) with the plate color sampled from the wiki
    renders, then keep the warm metal pixels (legs / trim) on top.
    """
    region = band[: to_row - offset_y, 9:246]
    warm_metal = (region[..., 0] - region[..., 2] > 10) & (region[..., :3].max(axis=-1) > 55)
    region[~warm_metal] = np.array(color, dtype=np.int16)


def _fill_pip_groove(band, np, zone, offset):
    """Replace the rank pip row with a uniform dark groove (per-row median).

    Row-wise fill keeps the groove's vertical gradient while removing the pip
    dots (the app draws its own rank pips).
    """
    x0, y0, x1, y1 = zone
    ox, oy = offset
    region = band[y0 - oy : y1 - oy, x0 - ox : x1 - ox]
    lum = region[..., :3] @ np.array([0.3, 0.6, 0.1])
    for row in range(region.shape[0]):
        dark = (lum[row] < 90) & (region[row, :, 3] > 200)
        fill = np.median(region[row, dark], axis=0) if dark.sum() >= 4 else np.array([26.0, 14.0, 12.0, 255.0])
        region[row, :, :] = fill


def _rail_mid(cards, np, box):
    """Extract the plain side border between the top and bottom bands.

    A plain median leaves mottled "mosaic" patches: behind the
    semi-transparent border each card's artwork differs, and for most rows
    (left y60-220, right y52-201) the median is art-biased. The border itself
    is vertically smooth, so keep only consensus-trusted pixels (all five
    cards agree within tolerance) and interpolate each column vertically
    across the dirty gaps; np.interp clamps the ends to the nearest trusted
    row. Intrusion ornaments the consensus keeps (leg tips near the band
    ends) are trusted pixels and pass through unchanged.
    """
    x0, _, x1, _ = box
    stack = np.stack(cards)[:, RAIL_MID_TOP:RAIL_MID_BOTTOM, x0:x1, :]
    spread = stack.max(axis=0) - stack.min(axis=0)
    trusted = (spread[..., :3].max(axis=-1) <= CONSENSUS_TOLERANCE) & (spread[..., 3] <= CONSENSUS_TOLERANCE)
    median = np.median(stack, axis=0)
    rows = np.arange(median.shape[0], dtype=np.float64)
    rail = np.zeros_like(median, dtype=np.float64)
    for x in range(median.shape[1]):
        t = trusted[:, x]
        if not t.any():
            continue
        rail[:, x, :] = np.column_stack([np.interp(rows, rows[t], median[t, x, c]) for c in range(4)])
    rail = rail.astype(np.int16)
    _strip_dark_edges(rail, np)
    # Light vertical smoothing (window 5) hides remaining per-row jitter; edge
    # rows are padded so the junction rows meeting the top/bottom bands stay
    # exact.
    padded = np.pad(rail.astype(np.float64), ((2, 2), (0, 0), (0, 0)), mode="edge")
    smoothed = np.stack([padded[i : i + rail.shape[0]] for i in range(5)]).mean(axis=0)
    rail[2:-2] = smoothed[2:-2].astype(np.int16)
    return rail


def _erase_rect(band, np, rect, offset):
    x0, y0, x1, y1 = rect
    ox, oy = offset
    band[y0 - oy : y1 - oy, x0 - ox : x1 - ox] = 0


def _erase_tab_text(tab, np):
    """Flatten the WARFRAME label inside the tab, keeping border and gradient.

    The label is gold with a dark outline, so thresholding leaves a ghost.
    Fill the whole text rect row-by-row with the clean interior color sampled
    just left of the text (inside the border, clear of the chevron caps).
    """
    x0, y0, x1, y1 = TAB_TEXT_RECT
    ox, oy = TAB_RECT[0], TAB_RECT[1]
    sx0, sx1 = TAB_FILL_SAMPLE[0] - ox, TAB_FILL_SAMPLE[1] - ox
    region = tab[y0 - oy : y1 - oy, x0 - ox : x1 - ox].astype(np.float64)
    source = tab[y0 - oy : y1 - oy, sx0:sx1].astype(np.float64)
    for row in range(region.shape[0]):
        fill = np.median(source[row].reshape(-1, 4), axis=0)
        region[row, :, :] = fill
    tab[y0 - oy : y1 - oy, x0 - ox : x1 - ox] = region.astype(np.int16)


def _save(array, np, name, scale=2):
    image = Image.fromarray(array.clip(0, 255).astype("uint8"), "RGBA")
    if scale != 1:
        image = image.resize((image.width * scale, image.height * scale), Image.Resampling.LANCZOS)
    image.save(OUTPUT / name)
    return image.size


def _tint(source_name: str, output_name: str, shadow: tuple[int, int, int], glow: tuple[int, int, int], scale: int = 2, opaque: bool = False) -> None:
    source = Image.open(OUTPUT / source_name).convert("RGBA")
    pixels = []
    for red, green, blue, alpha in source.getdata():
        if alpha == 0:
            pixels.append((0, 0, 0, 0))
            continue
        intensity = max(red, green, blue) / 255.0
        # opaque=True：卡体底板必须不透明，否则展开时下方槽位的内容会透上来
        if opaque:
            alpha = 255 if alpha >= 128 else 0
        pixels.append(tuple(round(shadow[index] * (1.0 - intensity) + glow[index] * intensity) for index in range(3)) + (alpha,))
    source.putdata(pixels)
    source.resize((source.width * scale, source.height * scale), Image.Resampling.LANCZOS).save(OUTPUT / output_name)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    cards, np = _load_cards()
    mask = _consensus_mask(cards, np)

    top = _band(cards, mask, np, TOP_BAND)
    _erase_cool_haze(top, np, 18, TOP_BAND[1])
    _strip_dark_edges(top, np)
    _save(top, np, "ArchonFrameTopHD.png")

    bottom = _band(cards, mask, np, BOTTOM_BAND)
    _flatten_plate(bottom, np, BOTTOM_PLATE_END, BOTTOM_BAND[1])
    _erase_rect(bottom, np, TAB_RECT, (BOTTOM_BAND[0], BOTTOM_BAND[1]))
    _fill_pip_groove(bottom, np, PIP_ZONE, (BOTTOM_BAND[0], BOTTOM_BAND[1]))
    _strip_dark_edges(bottom, np)
    _save(bottom, np, "ArchonFrameBottomHD.png")

    # 中段侧栏：只含顶/底框之间的纯橙色边框，CSS 用 object-fit:fill 桥接两框，
    # 折叠/展开同一几何，永远闭合。.mod-side-light-left 带 CSS scaleX(-1) 镜像，
    # 所以存储的左侧栏在此预镜像。
    _save(_rail_mid(cards, np, RAIL_LEFT)[:, ::-1], np, "ArchonSideMidHD.png")
    _save(_rail_mid(cards, np, RAIL_RIGHT), np, "ArchonSideMidRightHD.png")

    tab = _band(cards, mask, np, TAB_RECT, static_only=False)
    _erase_tab_text(tab, np)
    _strip_dark_edges(tab, np)
    _save(tab, np, "ArchonLowerTabHD.png")

    # Flat companion-app derived layers (no shader chrome involved).
    _tint("LegendaryBackground.png", "ArchonBackgroundHD.png", (21, 4, 5), (104, 24, 14), opaque=True)
    _tint("LegendaryTopRightBacker.png", "ArchonTopRightBackerHD.png", (58, 8, 8), (244, 139, 42))
    _tint("RankSlotActive.png", "ArchonRankSlotActiveHD.png", (125, 20, 10), (255, 220, 102))
    _tint("RankSlotEmpty.png", "ArchonRankSlotEmptyHD.png", (48, 6, 7), (150, 35, 18))
    _tint("RankCompleteLine.png", "ArchonRankCompleteLineHD.png", (111, 13, 8), (255, 179, 50))


if __name__ == "__main__":
    main()
