"""Run R8, the independent review, on patches that were shipped before R8 existed.

Each line of the input file is a JSON object with "run" (a label), "issue" (path to the issue
text), "patch" (path to the shipped filtered.diff) and "spec_tests" (the target test ids). The
review is the same call Receipts makes inside a run: src/receipts/verify/review.py with Nemotron 3
Super on Token Factory (thinking on, as REVIEWER_SETTINGS sets it), configured from .env.

Usage (from the receipts repository): .venv/bin/python trials/aeread/scripts/r8_check.py INPUT OUTPUT
Each patch gets the same independent reviews a run makes (REVIEW_VOTES); a veto needs all of
them to object. Writes one JSON line per patch to OUTPUT (resumable) and prints the total cost.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "src")
from receipts.cost import CostMeter  # noqa: E402
from receipts.llm import TokenFactoryClient, load_config  # noqa: E402
from receipts.patchscope import default_protected_modules  # noqa: E402
from receipts.verify.review import REVIEWER_SETTINGS, review_votes  # noqa: E402


async def main(source: Path, out: Path) -> None:
    meter = CostMeter()
    # The reviewer Receipts uses (REVIEWER_SETTINGS); REVIEW_MODEL, REVIEW_THINKING (1 or 0) and
    # REVIEW_TEMPERATURE override it, for exploring other settings.
    config = load_config(env_path=Path(".env")).model_copy(update=REVIEWER_SETTINGS)
    config = config.model_copy(update={
        "model": os.environ.get("REVIEW_MODEL", config.model),
        "thinking": os.environ.get("REVIEW_THINKING", "1" if config.thinking else "0") == "1",
        "temperature": float(os.environ.get("REVIEW_TEMPERATURE", config.temperature)),
    })
    print("reviewer", config.model, "thinking", config.thinking, "temperature", config.temperature, flush=True)
    model = TokenFactoryClient(config, env_path=Path(".env"), meter=meter)
    done = set()
    if out.exists():
        done = {json.loads(line)["run"] for line in out.read_text().splitlines() if line.strip()}
    for line in source.read_text().splitlines():
        task = json.loads(line)
        if task["run"] in done:
            continue
        result = await review_votes(
            model,
            Path(task["issue"]).read_text(encoding="utf-8"),
            task["spec_tests"],
            Path(task["patch"]).read_text(encoding="utf-8"),
            default_protected_modules(),
        )
        row = {"run": task["run"], "veto": result.veto, **result.model_dump(mode="json")}
        with out.open("a") as handle:
            handle.write(json.dumps(row) + "\n")
        print(task["run"], "VETO" if result.veto else "no veto",
              [len(vote.objections) for vote in result.votes],
              [vote.error for vote in result.votes if vote.error] or "", flush=True)
    print("cost", json.dumps(meter.summary()), flush=True)


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]), Path(sys.argv[2])))
