"""把 MOD / 架势立绘拆成伪 3D 视差双层（bg 不透明全图 + fg 主体抠图）。

DE 在每张立绘 PNG 的 alpha 通道里附带了主体遮罩（RGB 通道始终是完整不透明
画作），游戏内 hover 的假 3D 视差就是用这个遮罩分层合成的。本脚本离线复刻
这一步：对每张 X.png 生成
  X.bg.jpg  —— RGB 原样、alpha 强制不透明（视差里位移的背景层）
  X.fg.png  —— alpha 经 smoothstep(110, 200) 重映射的主体抠图（位移的前景层）

前端按同样的后缀约定推导路径；缺拆分素材时自动回退原始整图（只损失视差）。
在 sync_mod_assets.py 之后跑一次即可；重复运行会跳过已是最新的文件。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
ART_DIRS = (
    ROOT / "frontend" / "assets" / "mods" / "art",
    ROOT / "frontend" / "assets" / "stances" / "art",
)
# smoothstep 窗口：alpha < LO 视为背景（抠掉），> HI 视为主体（保留），中间软过渡。
# 该分布是对全量立绘统计后的取值（主体 alpha 普遍 >200，背景渐变集中在 <160）。
MASK_LO, MASK_HI = 110, 200
BG_QUALITY = 90


def split_one(src: Path) -> tuple[bool, str]:
    bg_path = src.with_suffix(".bg.jpg")
    fg_path = src.with_suffix(".fg.png")
    if (
        bg_path.is_file()
        and fg_path.is_file()
        and bg_path.stat().st_mtime >= src.stat().st_mtime
        and fg_path.stat().st_mtime >= src.stat().st_mtime
    ):
        return False, "skip"
    image = Image.open(src).convert("RGBA")
    alpha = np.asarray(image.getchannel("A"), dtype=np.float32)
    mask = np.clip((alpha - MASK_LO) / (MASK_HI - MASK_LO), 0.0, 1.0)
    mask = mask * mask * (3.0 - 2.0 * mask)
    fg = image.copy()
    fg.putalpha(Image.fromarray((mask * 255).astype(np.uint8)))
    fg.save(fg_path, optimize=True)
    image.convert("RGB").save(bg_path, quality=BG_QUALITY)
    return True, "ok"


def main() -> int:
    done = skipped = failed = 0
    for art_dir in ART_DIRS:
        if not art_dir.is_dir():
            continue
        for src in sorted(art_dir.rglob("*.png")):
            if src.stem.endswith((".bg", ".fg")):
                continue
            try:
                changed, _ = split_one(src)
                done += changed
                skipped += not changed
            except Exception as exc:  # noqa: BLE001 - 单张失败不阻断全量
                failed += 1
                print(f"[fail] {src}: {exc}", file=sys.stderr)
    print(f"split: {done} done, {skipped} up-to-date, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
