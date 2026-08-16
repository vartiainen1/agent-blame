"""Allow `python -m agent_blame ...`."""
import sys

from .cli import main

sys.exit(main())
