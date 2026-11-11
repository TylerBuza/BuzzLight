"""Double-click launcher (no console). Also what "Start with Windows" runs."""

import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)

from buzzlight.app import main  # noqa: E402

sys.exit(main())
