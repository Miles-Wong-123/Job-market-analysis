"""使 `python -m job_market` 等价于调用 CLI。"""

from job_market.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
