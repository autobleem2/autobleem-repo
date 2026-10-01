#!/usr/bin/env python3
"""Stage the download repository's page assets.

    repo_assets.py <outdir> [theme-dir]

Writes into <outdir> (what tools/repo_publish.sh assets uploads to <repo>/assets/) a copy of tools/site-assets/:

    background.jpg                           the ab2.0.0 theme's background - the page's picture under a dark gradient
    logo.png, logo@2x.png                    the C3 wordmark (the banner, the splash)
    emblem.png, emblem@2x.png                the "2" chip - the top bar's mark
    icon.png                                 the chip on graphite, 128x128 - the favicon and Raspberry Pi Imager's icon
                                             (copied to <repo>/rpi-imager/icon.png by the publish script)
    og.png                                   the social preview (1200x630)
    button-support[-hover][@2x].png          the Support button (the splash's Ko-fi link)
    RedHatText-Medium.ttf, -SemiBold.ttf     the page font (SIL OFL) and its OFL.txt

The files are the ones autobleem-design's www/ builds (www/make_www_assets.py from the ab2.0.0 theme's design
sources) - small enough to check in here, so staging needs nothing outside this repository. [theme-dir] is
still accepted (the publish script passes it on) and ignored: nothing is cut out of a theme any more.
"""

import os
import shutil
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(REPO, "tools", "site-assets")


def main():
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    out = sys.argv[1]
    if not os.path.isdir(SOURCE):
        sys.exit("repo_assets.py: %s is missing" % SOURCE)
    os.makedirs(out, exist_ok=True)
    for name in sorted(os.listdir(SOURCE)):
        shutil.copyfile(os.path.join(SOURCE, name), os.path.join(out, name))
    print("staged %s" % ", ".join(sorted(os.listdir(out))))


if __name__ == "__main__":
    main()
