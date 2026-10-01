import subprocess

from tests.fixtures.repo_factory import make_repo


def test_repo_has_one_failing_test(tmp_path):
    repo = make_repo(tmp_path)
    assert (repo / ".git").is_dir()
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
    assert len(head) == 40
    proc = subprocess.run(
        ["python", "-m", "pytest", "-q", "-o", "junit_family=xunit1", "--junitxml=report.xml", "-p", "no:cacheprovider"],
        cwd=repo, capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "1 failed, 3 passed" in proc.stdout


def test_flaky_repo_alternates(tmp_path):
    repo = make_repo(tmp_path, flaky=True)
    outcomes = []
    for _ in range(2):
        proc = subprocess.run(["python", "-m", "pytest", "-q", "tests/test_flaky.py", "-p", "no:cacheprovider"], cwd=repo, capture_output=True, text=True)
        outcomes.append(proc.returncode)
    assert outcomes == [1, 0]
