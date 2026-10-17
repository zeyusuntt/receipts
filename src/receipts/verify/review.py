"""R8: an independent Nemotron review of a patch the gate passed. It can only object.

The review runs in a fresh context: it sees the issue, the tests the patch already passes and
the source part of the patch, never the agent's reasoning or claims. Each objection must quote
the issue word for word and point at a line of the patch; plain code checks both and drops an
objection that does not, so a model can neither approve a patch nor reject one on a claim it
cannot ground.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from pydantic import BaseModel

from receipts.cost import TokenUsage
from receipts.llm import ModelClient
from receipts.patchscope import _parse_header, categorize

SYSTEM_PROMPT = """You review a patch that a coding agent wrote to resolve an issue. The patch already passes the tests the user named. Your only job is to find where the patch does not do what the issue asks. You can object; you cannot approve anything.

Report an objection only when both hold:
1. You can quote, word for word, a phrase or sentence of the issue that states a requirement.
2. You can point at a line of the patch, as path:line with the new-file line number shown in the annotated patch, where the patch fails that requirement, or breaks behavior that the issue says must keep working.

Do not object to style, naming, comments, missing tests, performance, or anything the issue does not ask for. Do not object because the patch differs from how you would have written it. If the patch meets every requirement in the issue, return an empty list of objections. A patch that passes its tests is usually correct; an objection you cannot prove from the issue and the patch is a mistake.

Answer with JSON only."""

PATCH_LIMIT = 60_000
# The reviewer's model settings: Nemotron 3 Super with thinking on, at a low temperature.
REVIEWER_SETTINGS = {"thinking": True, "temperature": 0.2}
# Independent reviews per patch. A veto needs every one of them to raise a grounded objection,
# so one review's sampling noise cannot reject a correct patch.
REVIEW_VOTES = 2
MIN_REQUIREMENT = 15
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_QUOTE_EDGES = ".\"'` \t\n"
_LINE_NUMBER = re.compile(r"[0-9]{1,9}")


class ReviewObjection(BaseModel):
    requirement: str
    location: str
    problem: str


class ReviewAnswer(BaseModel):
    objections: list[ReviewObjection]
    usage: TokenUsage | None = None
    retries: dict[str, int] | None = None

    @classmethod
    def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Keep provider bookkeeping out of the reviewer's response contract."""
        schema = super().model_json_schema(*args, **kwargs)
        schema.get("properties", {}).pop("usage", None)
        schema.get("properties", {}).pop("retries", None)
        schema.get("$defs", {}).pop("TokenUsage", None)
        return schema


class ReviewVotes(BaseModel):
    """The independent reviews of one patch, and whether they veto it."""

    votes: list["ReviewResult"]

    @property
    def veto(self) -> bool:
        return bool(self.votes) and all(vote.objections for vote in self.votes)


class ReviewResult(BaseModel):
    objections: list[ReviewObjection]
    dropped: list[ReviewObjection]
    prompt_sha256: str | None = None
    error: str | None = None
    usage: TokenUsage | None = None
    retries: dict[str, int] | None = None


ReviewVotes.model_rebuild()


def _source_blocks(patch_text: str, protected_modules: frozenset[str]):
    """(path, lines) for each source file of the patch, split on LF only, as git writes it."""
    path, keep, lines = None, False, []
    records = patch_text.split("\n")
    if records and records[-1] == "":
        records.pop()  # the newline that ends the patch, not an empty context line
    for line in records:
        header = _parse_header(line.rstrip("\r"))
        if header is not None:
            if path is not None and keep:
                yield path, lines
            path, _, parseable = header
            keep = parseable and categorize(path, protected_modules) == "source"
            lines = [line.rstrip("\r")]
        elif path is not None:
            lines.append(line.rstrip("\r"))
    if path is not None and keep:
        yield path, lines


def annotate_patch(
    patch_text: str,
    protected_modules: frozenset[str] = frozenset(),
    limit: int | None = None,
) -> tuple[str, dict[str, set[int]]]:
    """The source part of a patch with new-file line numbers, and the numbers shown, per file.

    With a limit, the text stops at the last whole line that fits, and only the lines shown
    count, so an objection can only point at code the reviewer was given.
    """
    out: list[str] = []
    lines_by_path: dict[str, set[int]] = {}
    size = 0
    truncated = False
    for path, lines in _source_blocks(patch_text, protected_modules):
        numbers = lines_by_path.setdefault(path, set())
        new_line = None
        for line in lines:
            number = None
            hunk = _HUNK.match(line)
            if hunk:
                # An empty new range (`+1,0`) names the line before the hunk.
                new_line = int(hunk[1]) + (1 if hunk[2] == "0" else 0)
                text = line
            elif new_line is None or line.startswith("\\"):
                text = line
            elif line.startswith("+"):
                text, number = f"+{new_line:>5} | {line[1:]}", new_line
                new_line += 1
            elif line.startswith("-"):
                text = f"-{'':>5} | {line[1:]}"
            elif line.startswith(" ") or line == "":
                text, number = f" {new_line:>5} | {line[1:]}", new_line
                new_line += 1
            else:
                text, new_line = line, None
            if limit is not None and size + len(text) + 1 > limit:
                truncated = True
                break
            out.append(text)
            size += len(text) + 1
            if number is not None:
                numbers.add(number)
        if truncated:
            break
    text = "\n".join(out) + ("\n" if out else "")
    if truncated:
        text += "[patch truncated]\n"
    return text, lines_by_path


def _normalized(text: str) -> str:
    return " ".join(text.split()).lower()


def ground(objection: ReviewObjection, issue: str, lines_by_path: dict[str, set[int]]) -> bool:
    """Whether the objection quotes the issue and points at a line the review was shown."""
    quote = _normalized(objection.requirement).strip(_QUOTE_EDGES)
    if len(quote) < MIN_REQUIREMENT or quote not in _normalized(issue):
        return False
    path, _, number = objection.location.strip().rpartition(":")
    if not _LINE_NUMBER.fullmatch(number) or int(number) < 1:
        return False
    if path not in lines_by_path and path.startswith(("a/", "b/")):
        path = path[2:]
    if int(number) not in lines_by_path.get(path, set()):
        return False
    return bool(objection.problem.strip())


def _user_prompt(issue: str, spec_tests: list[str], annotated: str) -> str:
    return (
        f"Issue:\n{issue}\n\n"
        "Tests the patch already passes:\n" + "".join(f"{test}\n" for test in spec_tests) + "\n"
        "Patch (source files only; each line starts with its line number in the new file):\n"
        f"{annotated}"
    )


async def review_patch(
    model: ModelClient,
    issue: str,
    spec_tests: list[str],
    patch_text: str,
    protected_modules: frozenset[str] = frozenset(),
) -> ReviewResult:
    annotated, lines_by_path = annotate_patch(patch_text, protected_modules, PATCH_LIMIT)
    if not lines_by_path:
        return ReviewResult(objections=[], dropped=[])
    user = _user_prompt(issue, spec_tests, annotated)
    prompt_sha256 = hashlib.sha256((SYSTEM_PROMPT + "\n\n" + user).encode("utf-8")).hexdigest()
    try:
        answer = await model.complete_json(SYSTEM_PROMPT, user, ReviewAnswer)
    except Exception as exc:  # a failed review never vetoes
        return ReviewResult(objections=[], dropped=[], prompt_sha256=prompt_sha256,
                            error=f"{type(exc).__name__}: {exc}"[:300])
    kept: list[ReviewObjection] = []
    dropped: list[ReviewObjection] = []
    for objection in answer.objections:
        try:
            grounded = ground(objection, issue, lines_by_path)
        except Exception:  # an answer the checks cannot read is not grounded
            grounded = False
        (kept if grounded else dropped).append(objection)
    return ReviewResult(objections=kept, dropped=dropped, prompt_sha256=prompt_sha256,
                        usage=answer.usage, retries=answer.retries)


async def review_votes(
    model: ModelClient,
    issue: str,
    spec_tests: list[str],
    patch_text: str,
    protected_modules: frozenset[str] = frozenset(),
    votes: int = REVIEW_VOTES,
) -> ReviewVotes:
    """Run independent reviews one after another; each sees nothing of the others."""
    results = [
        await review_patch(model, issue, spec_tests, patch_text, protected_modules)
        for _ in range(votes)
    ]
    return ReviewVotes(votes=results)
