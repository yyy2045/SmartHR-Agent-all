import asyncio
import json

from app.evaluation.mvp import run_mvp_evaluation


def main() -> None:
    report = asyncio.run(run_mvp_evaluation())
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    if not report.passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
