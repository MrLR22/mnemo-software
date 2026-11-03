# services/: ENGRAM as separate programs that talk over HTTP, so any part can be replaced or moved:
#   vlm/      big model service (Qwen today): frames → diary lines; needs a GPU (Kaggle while testing)
#   trigger/  small model service (our HOI-TCN): video → which 4-s windows need the big model; CPU
#   api/      backend: receives clips from the apps, runs the pipeline, keeps the diary, answers questions
# The apps (apps/web, apps/mobile) only talk to api/. See README.md.
#
# The model code and the diary / search code come from the research repository (../mnemo), found through
# $MNEMO_PATH (default: the mnemo folder next to this one). Nothing is copied, so a fix there is a fix here.

import os
import sys

MNEMO_PATH = os.environ.get("MNEMO_PATH", os.path.join(os.path.dirname(__file__), "..", "..", "mnemo"))
if not os.path.isdir(MNEMO_PATH):
    raise ImportError(f"ENGRAM needs the research code: set MNEMO_PATH (not found: {os.path.abspath(MNEMO_PATH)})")
if os.path.abspath(MNEMO_PATH) not in sys.path:
    sys.path.insert(0, os.path.abspath(MNEMO_PATH))
