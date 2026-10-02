# Nemotron tool-calling and structured-output spike (2026-09-30)

Throwaway probe: `spikes/nemotron_probe.py`. Raw results in the session scratchpad (`results.json`, `results_p2_rerun.json`). 365 API calls, 0 API errors, total spend about 0.034 USD.

## Verdict

1. Planner: use `nvidia/nemotron-3-super-120b-a12b` with `response_format=json_schema` (strict) and thinking off. 20/20 valid and schema-valid across both Super modes, zero reasoning leaks into `content`; thinking off is 2x faster and 3.5x fewer completion tokens with no observed accuracy loss.
2. Edit loop: use Super, thinking off, `tools=` with the three actions and `chat_template_kwargs={"enable_thinking": false}`. 9/10 loops reached `finish` with a correct fix within 6 turns (the one miss was still on-task, running the full suite on turn 6); 0 malformed arguments, 0 hallucinated tools, 0 multi-call turns. Do not use Nano for the loop: 0/20 loops finished correctly because it invents a `str_replace_editor` tool that is not in the tool list (16 of 60 turns), even after being told the tool does not exist.
3. Repair step: not needed for JSON (no invalid JSON in 80 structured calls) or for argument JSON (0 malformed in 365 calls). The loop still needs a guard for unknown tool names and for `finish` called before any `write_file`, both seen only on Nano, but cheap insurance on Super too.

## Results table

N = trials. Loop rows combine the first run and the rerun (rerun returns an error for unknown tool names instead of "ok"). Wall time is per API call, except p2 where it is the sum over the loop's turns. Ultra: one call only (cost). Long context: 71k prompt tokens (my 60k estimate undershot).

| model, mode | p1 single tool call | p2 loop finish+fix (turns with hallucinated tool / free text / 2 calls) | p3 tool_choice required | p3 tool_choice named | p4 json_schema strict (leaks) | p4 json_object (leaks) | p6 71k-token needle | p1 median wall s / completion tok | p4 schema median wall s / tok |
|---|---|---|---|---|---|---|---|---|---|
| Super, thinking on | 10/10 | 5/5 (0 / 0 / 0) | 5/5 | 5/5 | 10/10 (0) | 10/10 (0) | 1/1 | 1.03 / 42 | 2.31 / 226 |
| Super, thinking off | 10/10 | 9/10 (0 / 0 / 0) | 5/5 | 5/5 | 10/10 (0) | 10/10 (0) | 1/1 | 1.04 / 40 | 1.16 / 62 |
| Nano, thinking on | 10/10 | 0/10 (7 / 1 / 0) | 5/5 | 5/5 | 10/10 (0) | 10/10 (0) | not run | 2.93 / 178 | 3.88 / 271 |
| Nano, thinking off | 10/10 | 0/10 (9 / 0 / 0) | 5/5 | 5/5 | 10/10 (0) | 10/10 (0) | 0/1 (answered the value 42, not the line) | 0.85 / 35 | 2.36 / 136 |
| Ultra, thinking on | 1/1 | not run | not run | not run | not run | not run | not run | 0.92 / 74 | n/a |

Loop cost per completed 6-turn loop (median completion tokens summed): Super off 263 to 363, Super on 353, Nano off 204, Nano on 864 to 878. Nano thinking-on had one turn that spent 2998 completion tokens reasoning before emitting a call (hit close to the 3000 cap).

Probe 1 detail: p1 hallucinated-tool count was 0 for all modes. Super thinking-off returns a short narration sentence in `content` alongside the tool call (10/10); thinking-on returns empty `content` and puts 8 to 10 tokens of reasoning in the `reasoning` field. Neither breaks parsing.

## Request parameters that worked

Common: `openai` Python SDK 3.22.1, `base_url=https://api.tokenfactory.nebius.com/v1/`, `temperature=1.0, top_p=0.95` (NVIDIA model card recommendation for all tasks), `timeout=180, max_retries=2`.

Thinking toggle (verified on Super and Nano; the reasoning comes back in `message.reasoning` and `message.reasoning_content`, never in `content`):

```python
extra_body={"chat_template_kwargs": {"enable_thinking": False}}   # or True
```

Tool calling (probe 1, 2):

```python
client.chat.completions.create(
    model="nvidia/nemotron-3-super-120b-a12b",
    messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": task}],
    tools=TOOLS,                       # standard OpenAI function schemas
    max_tokens=2000,                   # 3000 for loop turns
    temperature=1.0, top_p=0.95,
    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
)
```

Feeding tool results back: append `{"role": "assistant", "content": m.content or None, "tool_calls": [...]}` (drop the `reasoning` fields) then one `{"role": "tool", "tool_call_id": tc.id, "content": ...}` per call. Worked on every turn.

tool_choice: both `tool_choice="required"` and `tool_choice={"type": "function", "function": {"name": "run_command"}}` were honoured 5/5 on every mode, even though the Token Factory docs only list `auto` and the named form.

Structured output (probe 4):

```python
response_format={"type": "json_schema", "json_schema": {"name": "fix_plan", "strict": True, "schema": PLAN_SCHEMA}}
# PLAN_SCHEMA: object with plan:str, files_to_edit:[str], test_command:str, confidence:number 0..1,
# all required, additionalProperties false
```

`{"type": "json_object"}` with the keys described in the prompt also gave 40/40 valid and schema-valid, so it is a fine fallback.

System prompt used for the loop: "You are an autonomous coding agent operating on a git repository. You act only by calling tools. Call exactly one tool per turn. Do not ask the user questions. When the task is done, call finish."

## Failure modes seen (one raw example each, truncated)

1. Hallucinated tool name (Nano only, both modes, 16 of 60 loop turns). The tool list had run_command, write_file, finish. Nano repeatedly called `str_replace_editor`, including after receiving `error: unknown tool 'str_replace_editor'. Available tools: run_command, write_file, finish.`
   Raw: `{"name": "str_replace_editor", "arguments": "{\"path\": \"src/x.py\", \"command\": \"view\"}"}` and once `{"path": "src/x.py", "command": "write", "value": "def add(a, b):\n    return a + b"}`.
2. finish before fixing (Nano off, 2 of 10 loops). After `cat src/x.py` it called finish with a diagnosis and never wrote the file.
   Raw: `{"name": "finish", "arguments": "{\"summary\": \"The test failure is due to the `add` function in `src/x.py` returning `a + b - 1` instead of the expected sum `a + b`..."}`
3. Loop does not converge in 6 turns (Nano, 17 of 20; Super off, 1 of 10). Nano loops looped on view/cat. The Super case did the fix correctly and used turn 6 to run the full suite.
   Raw (Super, turn 5): content `Perfect! The test now passes. Let me also run all tests to make sure I...` with `run_command {"cmd": "python -m pytest tests/ -v"}`.
4. Free text instead of a tool call (Nano on, 1 turn of 60). Content was empty; only reasoning came back, no tool_calls. A nudge message ("You must respond with a tool call") recovered it next turn.
   Raw: content `''`, reasoning `We need to inspect the repository structure. We found source file src/x.py and t...`, tool_calls `[]`.
5. Bad shell command string (Nano off, once). `{"cmd": "cat from src/x.py"}`. Valid JSON, wrong command.
6. Long context comprehension miss (Nano off, 1 of 1). Asked for the line number holding `NEEDLE_7F3A = 42`; Nano answered `42`. Super answered `1331` correctly in both modes (thinking on spent 440 completion tokens, off spent 9).
7. Path drift in structured output (Super on, 1 of 10; still schema-valid). `"files_to_edit": ["/absolute/path/to/repo/src/x.py"]` instead of `src/x.py`.

Not seen anywhere: malformed argument JSON (0/365), invalid or non-schema JSON in structured mode (0/80), reasoning text leaking into content (0/80), two tool calls in one turn (0), API errors or rate limiting at 8 concurrent workers (0), tool_choice ignored (0).

## Latency and tokens (probe 5)

Per call, from probe 1 (tool call) and probe 4 (json_schema):

| mode | tool call wall s / tok | json_schema wall s / tok | json_object wall s / tok |
|---|---|---|---|
| Super on | 1.03 / 42 | 2.31 / 226 | 1.77 / 209 |
| Super off | 1.04 / 40 | 1.16 / 62 | 0.91 / 58 |
| Nano on | 2.93 / 178 | 3.88 / 271 | 3.88 / 214 |
| Nano off | 0.85 / 35 | 2.36 / 136 | 1.63 / 100 |

Super with thinking on barely reasons when tools are present (8 to 10 reasoning tokens), so thinking mode costs nothing extra there; it does reason on the structured-output planner call (about 160 extra tokens). Nano is not faster than Super on this endpoint.

## Spend

Pricing used for the estimate: Super and Nano 0.06 USD/M input, 0.24 USD/M output (Token Factory list price seen via OpenRouter's provider table; not read from a Nebius pricing page, so UNVERIFIED). Ultra placeholder 1.00/3.00.

- Main run: 279 calls, 346,748 prompt tokens, 30,069 completion tokens, 0.0287 USD, 256 s wall.
- Loop rerun: 86 calls, 60,950 prompt, 7,017 completion, 0.0053 USD, 101 s.
- Smoke calls before the script: 3 calls, under 0.001 USD.
- Total about 0.034 USD.

## Not done / UNVERIFIED

- Ultra: one tool call only; no loop, structured, or long-context data.
- Lightning (nvidia/Nemotron-3_5-Lightning): not tested.
- `force_nonempty_content` chat_template_kwarg (recommended by the NVIDIA model card for coding agents): not tested; not needed since parsing never failed.
- `reasoning_budget` / `low_effort` kwargs: not tested.
- N is small (5 to 10). A 0/10 vs 9/10 gap is meaningful; a 9/10 vs 10/10 gap is not.
- The fake repo is trivial; real repos will stress the loop harder than this did.
- Streaming with tool calls: not tested.
