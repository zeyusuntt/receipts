# SWE-rebench for a local Docker pilot (2026-10-01)

Research by a subagent; nothing was pulled or run, so container steps are UNVERIFIED. Host: arm64, Docker 28.5.2.

## Datasets
- V1 `nebius/SWE-rebench` (CC-BY-4.0, Python only): `test` 21,336 rows; `filtered` 6,542 rows with `docker_image` set. https://huggingface.co/datasets/nebius/SWE-rebench
- V2 `nebius/SWE-rebench-V2` (CC-BY-4.0, per-repo license): `train` 32,079 rows, 20 languages; 7,243 Python rows from 691 repos, all `parse_log_pytest` with a pytest `test_cmd`. https://huggingface.co/datasets/nebius/SWE-rebench-V2
- Leaderboard `nebius/SWE-rebench-leaderboard`: `test` 860 rows plus monthly splits.
- Shared fields: `instance_id`, `repo`, `base_commit`, `patch` (gold), `test_patch` (adds F2P tests), `problem_statement`, `FAIL_TO_PASS`, `PASS_TO_PASS` (pytest node ids), `install_config.test_cmd`, `install_config.log_parser`.
- V2 extras: `language`, `image_name`, `interface`, `meta.llm_metadata.difficulty` (Python: easy 2,220, medium 4,646, hard 354), `meta.num_modified_files`, `meta.num_modified_lines`.

## Images
- V1: `swerebench/sweb.eval.x86_64.<owner>_1776_<repo>-<PR>:latest`, about 1.3 GB compressed, conda env `/opt/conda/envs/testbed`, repo at `/testbed` (unverified), test patch not applied.
- V2: `docker.io/swerebenchv2/<owner>-<repo>:<PR>-<sha7>`, about 0.8 GB, system Python, repo at `/<reponame>` (WORKDIR), base commit checked out and install done, git history stripped, test patch not applied. Build template: https://github.com/SWE-rebench/SWE-rebench-V2
- All checked images are linux/amd64 only: on this Mac they run under emulation (enable Rosetta in Docker Desktop; expect 3.7x to 7x slower than native per https://greynewell.com/blog/swe-bench-arm64-native-containers-6x-faster/). Allocate about 120 GB disk and 8+ CPUs.

## Official evaluation
- V1 harness https://github.com/SWE-rebench/SWE-bench-fork: apply model patch, reset test files, apply `test_patch`, run `test_cmd` plus the test files, parse the `-rA` summary with `parse_log_pytest` (splits on whitespace, so ids with spaces are truncated); resolved = every F2P and P2P test PASSED or XFAIL; a missing test counts as failed.
- V2 `scripts/eval.py`: apply model patch and test patch with `git apply --3way --recount --ignore-space-change --whitespace=nowarn`, run `test_cmd`, parse; resolved is our rule: all F2P passed and no P2P failed.
- Reproducible ourselves: run the dataset `test_cmd` with `-rA`, keep the full stdout, apply `parse_log_pytest`, compare with F2P and P2P.

## Token Factory Sandboxes
Docs list SWE-bench Verified, SWE-rebench filtered and SWE-rebench-V2 as preloaded but give no tags; mini-swe-agent passes `image_name` or `docker_image` to `images.oci`, so preloaded tags are probably the dataset image names (unverified until access is granted: `contree images --prefix=swerebench`).

## First candidates
V2 easy, one file, at most 6 changed lines: `pycqa__docformatter-254`, `wntrblm__nox-903`, `neogeny__tatsu-276`. V1 filtered, one file, one F2P test: `asottile__all-repos-322`, `cdent__gabbi-238`, `auth0__auth0-python-40`, `chriskuehl__rustenv-12`.
