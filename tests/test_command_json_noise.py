import hashlib
import json
import shlex
import subprocess
import sys

import pytest

from receipts import orchestrate
from receipts.llm import FakeModel
from receipts.rundir import RunDirectory
from receipts.sandbox.protocol import ImageSource
from tests.test_daytona_executor import (
    MemoryDaytonaApi,
    _daytona_module,
    _executor as daytona_executor,
)
from tests.test_tokenfactory_executor import (
    _dynamic_fake,
    _executor as tokenfactory_executor,
    _module as tokenfactory_module,
)


MARKER = "RECEIPTS_TEST_DIGESTS_JSON:"
NOISE = "Error processing line 1 of /usr/local/lib/python3.10/site-packages/example-nspkg.pth:\n"


@pytest.mark.parametrize(
    ("backend", "noise_position"),
    [
        ("tokenfactory", "before"), ("tokenfactory", "after"),
        ("daytona", "before"), ("daytona", "after"),
        ("daytona", "before-no-newline"),
    ],
)
async def test_disclosure_parses_only_marked_json_with_stderr_noise(
    tmp_path, monkeypatch, backend, noise_position,
):
    repository = tmp_path / "repository"
    (repository / "tests").mkdir(parents=True)
    test_bytes = b"def test_sample():\n    assert True\n"
    config_bytes = b"[pytest]\n"
    (repository / "tests/test_sample.py").write_bytes(test_bytes)
    (repository / "pytest.ini").write_bytes(config_bytes)

    def execute(command):
        # Run the actual in-sandbox producer, with Python startup noise on stderr.
        script = shlex.split(command)[2]
        noise = NOISE.rstrip("\n") if noise_position == "before-no-newline" else NOISE
        noise_script = f"import sys; sys.stderr.write({noise!r}); sys.stderr.flush()\n"
        script = (
            noise_script + script if noise_position.startswith("before")
            else script + "\n" + noise_script
        )
        return subprocess.run(
            [sys.executable, "-c", script], cwd=repository,
            capture_output=True, text=True, check=False,
        )

    if backend == "tokenfactory":
        def handler_for_run(call):
            def handler(tree):
                result = execute(call["command"])
                return result.returncode, result.stdout, result.stderr, tree
            return handler

        api = _dynamic_fake(handler_for_run)
        executor, _, _ = tokenfactory_executor(tmp_path, tokenfactory_module(), api)
    else:
        module = _daytona_module()

        class NoisyDaytonaApi(MemoryDaytonaApi):
            async def exec(self, sandbox_id, command, **kwargs):
                if not command.startswith("python -c "):
                    return await super().exec(sandbox_id, command, **kwargs)
                result = execute(command)
                output = (
                    result.stderr + result.stdout if noise_position.startswith("before")
                    else result.stdout + result.stderr
                )
                return module.DaytonaCommandResult(
                    exit_code=result.returncode, output=output,
                )

        executor, _, _ = daytona_executor(tmp_path, module, NoisyDaytonaApi(module))

    base = await executor.prepare(ImageSource(image="swerebenchv2/example:1", workdir="/repo"))

    async def collect(name):
        return await orchestrate._collect_disclosure(
            executor, base, FakeModel(), executor,
            ["tests/test_sample.py::test_sample"], RunDirectory(tmp_path / name),
        )

    try:
        disclosure = await collect("valid")
        assert disclosure.test_digests == {
            "tests/test_sample.py": hashlib.sha256(test_bytes).hexdigest(),
        }
        assert disclosure.pytest_config_digests == {
            "pytest.ini": hashlib.sha256(config_bytes).hexdigest(),
        }

        # Noise must never turn absent, malformed, or ambiguous evidence into success.
        valid_json = json.dumps({"test_digests": {}, "pytest_config_digests": {}})
        for name, output in [
            ("missing", valid_json + "\n"),
            ("invalid", MARKER + "{broken}\n"),
            ("duplicate", (MARKER + valid_json + "\n") * 2),
        ]:
            script = f"print('\\n' + {output!r}, end='')"
            monkeypatch.setattr(
                orchestrate, "_digest_command",
                lambda _, script=script: "python -c " + shlex.quote(script),
            )
            with pytest.raises(RuntimeError, match="test digest command returned invalid JSON"):
                await collect(name)
    finally:
        await executor.close()
