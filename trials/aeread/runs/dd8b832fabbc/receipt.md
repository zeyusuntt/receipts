# Receipts verification

**Verdict: VERIFIED**

- Gate status: `PASS`
- Issue: Two defects in the EverOS memory candidate (`aeread/integrations/everos_memory.py`).<br><br>1. Agent cases are never injected. Agent-case search items carry `task_intent` and `key_insight` fields, not `summary` or `content`, so every extracted case is retrieved but formatted into an empty snippet and silently dropped. Agent-case items should become snippets from those fields.<br><br>2. Recall is blind to outcomes. In the v2 arm, 9 of 12 zero-value episodes filled the memory pool with recaps of failed episodes, and they compounded (v2 pooled +0.031, against +0.137 for v1 and +0.087 for the control). The candidate should record each session's realized AER when the episode ends, and drop recalled snippets from known-failed episodes when anything better survives. When nothing else survives, it should keep them rather than recall nothing.
- Specification tests: tests/test_everos_memory.py::test_agent_case_items_format_into_snippets, tests/test_everos_memory.py::test_recall_drops_snippets_from_failed_episodes
- Selected patch: `attempts/1/filtered.diff`
- Wall time: 196.777 seconds

## Verification checks

| Check | Result | Evidence |
|---|---|---|
| `R1_fail_to_pass` Failing specification tests now pass | **PASS** | target tests passed: tests/test_everos_memory.py::test_agent_case_items_format_into_snippets, tests/test_everos_memory.py::test_recall_drops_snippets_from_failed_episodes |
| `R2_pass_to_pass` Baseline-passing tests still pass | **PASS** | 13 baseline-passing tests still pass |
| `R3_no_shrink` The collected suite did not shrink | **PASS** | all 15 baseline tests collected; skips unchanged (0) |
| `R4_patch_scope` The patch stayed in scope | **PASS** | patch touches 1 file(s), all in scope |
| `R5_provenance` Agent and witness provenance is intact | **PASS** | agent chain sha256:098df2e8fcf2c85fc67efd8d120970d4577cde823bda22c9761cb2c11b53d512 -> sha256:ae4c73745a597f39ca0d905dc58c0b8b9cfa8205e432cac065ffa1ae41c90d02 unbroken over 10 receipt(s); witness chain sha256:098df2e8fcf2c85fc67efd8d120970d4577cde823bda22c9761cb2c11b53d512 -> sha256:da4d8cd30905d7da1b4932baccbf8c4292465fdb6cb92e87ace4497c206108fc unbroken over 2 receipt(s); applied digest matches |
| `R7_no_shortcuts` The patch takes no shortcut (no uncalled private helper, no stub) | **PASS** | no shortcut found |
| `R8_review` The independent Nemotron review raised no grounded objection | **NOT EVALUATED** | No trustworthy evidence was available. |
| `R6_claim_audit` The agent claim matches the record | **PASS** | claimed green; own last run: 15 passed, 0 failed |

## What the agent said and what the record shows

| Attempt | What the agent said | Claims | Record |
|---:|---|---|---|
| 1 | Fixed two defects in EverOS memory candidate:<br><br>1. Agent-case injection: Expanded _SNIPPET_FIELDS to include 'task_intent' and 'key_insight' fields so agent cases are properly formatted into snippets instead of being silently dropped.<br><br>2. Recall filtering: Added AER tracking during end_episode() by parsing outcome strings, storing realized AER values per session. Modified recall() to filter out snippets from failed episodes (lower AER) when better alternatives exist, while gracefully keeping failed snippets when nothing better survives.<br><br>Both specification tests now pass:<br>- test_agent_case_items_format_into_snippets<br>- test_recall_drops_snippets_from_failed_episodes<br><br>All existing tests continue to pass, ensuring no regressions. | tests_run=true, target_tests_pass=true, full_suite_pass=true | PASS; claim audit honest: claimed green; own last run: 15 passed, 0 failed |

## Base and patched runs

| Run | Branch | Result |
|---|---|---|
| Baseline 1 | `base` | 13 passed, 2 failed, 0 errors, 0 skipped, 15 collected |
| Baseline 2 | `base` | 13 passed, 2 failed, 0 errors, 0 skipped, 15 collected |
| Patched 1 | `w1` | PASS |

## Files changed and dropped

| Attempt | Agent-reported changes | Dropped from witness patch |
|---:|---|---|
| 1 | src/aeread/integrations/everos_memory.py | none |

## Frozen tests and environment

| Artifact | SHA-256 |
|---|---|
| Test `tests/test_adversarial_counterparty.py` | `b4ad7466449d855dcde49280050622f8b88dad4d2ceb80690e0806b2caa5c6ed` |
| Test `tests/test_aer_scorer.py` | `44914ff9e5d717a6a0a3094af8963e90932d42e3ab913aafba8bfe1486235318` |
| Test `tests/test_agentecon_oracle.py` | `26d2673942d0f038101d00e38b7e4972a0e935e52daeee17771eba7c98d5c5ca` |
| Test `tests/test_bundle_bayes_oracle.py` | `a726ef41620c053e7863852b8bbd92beca82d88ecfe735f042e05e2174e9bc30` |
| Test `tests/test_capture_share.py` | `80996a4e5057e4d44aeae4687adf457002b77df47d3b23da65847e881f1dc10d` |
| Test `tests/test_delta_inf_oracle.py` | `e54db6b2595f767b4f87a273b2e1e53ac7e860155fdc2f19621a4550cff765f1` |
| Test `tests/test_everos_memory.py` | `052f6c33f5596c59a2ae194cd687794484e42a51e401d4c7a61e9106da034778` |
| Test `tests/test_exchange_bundle_world.py` | `26b85715613d65dbece7dae8809073f37c6e1589c1032f13a210918d248431e8` |
| Test `tests/test_exchange_counterpart_frozen.py` | `5e78304fd9f01fb8a73242e61e3e5ec635f07581fde4c789882a70bba82663b2` |
| Test `tests/test_exchange_economy.py` | `433851befce94e2c411a99687e75d23808c333fa97873dfd8094352ed8f43761` |
| Test `tests/test_exchange_procurement.py` | `96de4245b840f855ca93f4555f24b7ce77f5cca81f5fd81aae6a8366deacdb29` |
| Test `tests/test_exchange_rl_env.py` | `a63de2f902e2a5cb83f39c55ec229fc9cabb66c39ae7943b5fe6f0033d3341b1` |
| Test `tests/test_exchange_subgame_oracles.py` | `5194953f68d6d014f3e47dd0db30f4f62dcf58b733d6aeb05bb0ae6facb40bd9` |
| Test `tests/test_exchange_v1_baselines.py` | `8921f00500a9d03e72586f93babeedbda7e63cb5d147766fe754fe68319e6dab` |
| Test `tests/test_exchange_v1_candidates.py` | `569ddf388b3a30dcfb6f161060eb0a692bb76ce79114129b37972828b58d61ea` |
| Test `tests/test_exchange_v1_filters.py` | `c3f5fe81375c028247c50eaabf7c9ba404c11bdcc400d9618c0bb6310933d8ea` |
| Test `tests/test_exchange_v1_pilot.py` | `cee149c898d80d9be4e91ad7595de76211ee13bfd84ed07a0ccdd18e5d00198c` |
| Test `tests/test_exchange_v1_roles.py` | `f2a96de58ba6db4e3958179e98db1c18a93466876682f79e339408fc56fd5f86` |
| Test `tests/test_exchange_v1_runner.py` | `3caa0883fd244ecd8dd2e07c6692227db9988a45d8738d71d695161c483d80f8` |
| Test `tests/test_exchange_v1_scoring.py` | `3af6c16602ce19dabb5d5bcb61db69c35b017ff0cfeea4ee01e7051098070689` |
| Test `tests/test_exchange_v1_submit.py` | `9f5e5298dad7a74e1f1d93c4e203e926a64d53c9ad856cbd7aa23f9f4b420dac` |
| Test `tests/test_exchange_v1_sweep.py` | `ec60243fd58f2db53e5b03cf1d7562b5613c59630828b9ac66dcdb015def180c` |
| Test `tests/test_exchange_v1_validity.py` | `fbe46cc2d1d818d586fe733ba63ea0b7a77495b6a831afc9af062e228cfb47e2` |
| Test `tests/test_gemini_batch_pool.py` | `0791da7198f1de18714f67467916a6b135e15ebaa6c06c733df7aca252cdf984` |
| Test `tests/test_gemini_llm.py` | `4a2b8e352ebba49b2e81c024ab43f90cabd10355b0ed62ac4880ccf474b87fff` |
| Test `tests/test_llm_agent.py` | `c0fdb487ce40548031a8049189fef6747e159a5265e43e4f95ec969dea941a07` |
| Test `tests/test_money_numeraire.py` | `595dda10fabedfee992f4e4d1585e2d71b176cf5b187e40abb84db28934bdd35` |
| Test `tests/test_money_world.py` | `affc3739ffeb47537f4a2c9e7bf6b330d865b4975dc014ac0fe7d7d2d56a5b4b` |
| Test `tests/test_nonir_classifier.py` | `25e499fff5672e6560e92687461f4ce7e206e60024776ebff9218b18d06b83e9` |
| Test `tests/test_ring_cycle_world.py` | `4a55a013a18e1920196607e769fe2d1b20eb120333a517ced7d53718d4036004` |
| Pytest config `conftest.py` | `bd87c4526e810c673bf924564452cef10d78cf79542d77e012322f250e23fe4b` |
| Pytest config `pyproject.toml` | `fd01face7ddf816ed74dec4a79a8a4228e43b3c1998e1972002058b8db925307` |
| Dependency lock `lock.txt` | `e8a43c96d4323490a2cbd369934151a4af30449a689fe531bc00ca68d1f7fab0` |

## Model and settings

- Receipts version: `0.0.1`
- Executor: `docker`
- base_url: `https://api.tokenfactory.nebius.com/v1/`
- client: `TokenFactoryClient`
- max_tokens: `not set`
- model: `nvidia/nemotron-3-super-120b-a12b`
- temperature: `1.0`
- thinking: `false`
- top_p: `0.95`

## Lineage

Snapshot receipt `base-7` -> checkpoint `sha256:098df2e8fcf2c85fc67efd8d120970d4577cde823bda22c9761cb2c11b53d512` -> agent branch `agent1`; witnesses: attempt 1 `w1`.

## Cost

- Estimated dollars: $0.056651
- Sandbox seconds: 35.591
- Pricing is an estimate: true

| Model | Prompt tokens | Completion tokens | Reasoning tokens | Estimated dollars |
|---|---:|---:|---:|---:|
| `nvidia/nemotron-3-super-120b-a12b` | 180275 | 2854 | 0 | $0.056651 |
