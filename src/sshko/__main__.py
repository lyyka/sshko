"""Enable `python -m sshko`."""

import sys

from sshko.cli import main

if __name__ == "__main__":
    sys.exit(main())
