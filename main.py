"""Auto Draw Studio — ponto de entrada."""
import sys

from app.ui.main_window import run_app


def main() -> int:
    return run_app(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
