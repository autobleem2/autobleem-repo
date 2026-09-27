#!/usr/bin/env python3
"""Stage the download repository's page assets from the ab2 theme.

    repo_assets.py <outdir> [theme-dir]

Writes into <outdir> (what tools/repo_publish.sh assets uploads to <repo>/assets/):

    hero.jpg            the theme's background - the AutoBleem 2 logo is painted into it
    icon.png            the emblem cut out of it, 128x128 - the page's favicon and Raspberry Pi Imager's icon
                        (copied to <repo>/rpi-imager/icon.png by the publish script)
    selawik-light.ttf   the theme's font (SIL OFL) and its OFL.txt

This repo carries none of the theme itself (no autobleem-themes submodule here - that repo is the
launcher's). <theme-dir> must point at a checkout of autobleem2/autobleem-themes' Themes/ab2 (or any
directory laid out the same way): a sibling checkout's `../autobleem-themes/Themes/ab2` works from this
repo's own tools/ the same way `../pcsx-abnxt/...` does for tools/repo_publish.sh's `pcsx` kind. Give it
either as the second argument or as the AB_AB2_THEME_DIR environment variable (the argument wins); there is
no built-in default, on purpose, since there is nothing under this repo to default to.

Nothing here is duplicated in git: the sources stay wherever <theme-dir> points. icon.png is cut out with
Pillow, or copied from tools/repo_icon.png (the same cut, checked in for a python without Pillow - MSYS2's).
"""

import os
import shutil
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# where the emblem sits in abback2.jpg (1280x720): the "A" with the pad, above the wordmark
EMBLEM_BOX = (430, 90, 850, 440)


def main():
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    out = sys.argv[1]
    theme = sys.argv[2] if len(sys.argv) == 3 else os.environ.get("AB_AB2_THEME_DIR")
    if not theme:
        sys.exit(
            "repo_assets.py: no theme directory given - pass it as the second argument or set "
            "AB_AB2_THEME_DIR (a checkout of autobleem2/autobleem-themes' Themes/ab2). See the module "
            "docstring (repo_assets.py -h)."
        )
    if not os.path.isdir(theme):
        sys.exit("repo_assets.py: theme directory not found: %s" % theme)
    os.makedirs(out, exist_ok=True)
    for src, dst in (("abback2.jpg", "hero.jpg"), ("selawik-light.ttf", "selawik-light.ttf"), ("OFL.txt", "OFL.txt")):
        shutil.copyfile(os.path.join(theme, src), os.path.join(out, dst))
    try:
        from PIL import Image
    except ImportError:
        shutil.copyfile(os.path.join(REPO, "tools", "repo_icon.png"), os.path.join(out, "icon.png"))
        print("staged %s (icon.png from tools/repo_icon.png - no Pillow here)" % ", ".join(sorted(os.listdir(out))))
        return
    with Image.open(os.path.join(theme, "abback2.jpg")) as im:
        emblem = im.crop(EMBLEM_BOX)
        side = max(emblem.size)
        square = Image.new("RGB", (side, side), (7, 34, 74))
        square.paste(emblem, ((side - emblem.width) // 2, (side - emblem.height) // 2))
        square.resize((128, 128), Image.LANCZOS).save(os.path.join(out, "icon.png"), optimize=True)
    print("staged %s" % ", ".join(sorted(os.listdir(out))))


if __name__ == "__main__":
    main()
