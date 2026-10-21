"""release.yaml runs tests/test_ffmpeg_binary.py on the ffmpeg / ffprobe each build ships, before anything is uploaded,
and keeps the update signing key in a job with a read-only token that installs nothing but the pinned yt-dlp wheel."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEST_STEP = "- name: Test the Bundled ffmpeg 🧪"
TEST_RUN = "run: python -m pytest -q tests/test_ffmpeg_binary.py"


def _spec_names():
    """The COLLECT directory and the .app bundle the PyInstaller spec builds."""
    (spec,) = ROOT.glob("*.spec")
    text = spec.read_text(encoding="utf-8")
    collect = re.search(r'^coll = COLLECT\(.*?^\s+name="([^"]+)"', text, re.M | re.S).group(1)
    bundle = re.search(r'BUNDLE\(.*?name="([^"]+\.app)"', text, re.S).group(1)
    return collect, bundle


def _steps(job):
    """The steps of ``job`` in release.yaml, each as its own text."""
    text = (ROOT / ".github/workflows/release.yaml").read_text(encoding="utf-8")
    body = re.search(rf"^  {job}:\n(.*?)(?=^  \S|\Z)", text, re.M | re.S).group(1)
    return ["- " + step for step in re.split(r"^      - ", body, flags=re.M)[1:]]


def _jobs():
    """Every job of release.yaml by id, each as its own text."""
    text = (ROOT / ".github/workflows/release.yaml").read_text(encoding="utf-8")
    body = text.split("\njobs:\n", 1)[1]
    return dict(re.findall(r"^  (\S+):\n(.*?)(?=^  \S|\Z)", body, re.M | re.S))


def _index(steps, line):
    found = [i for i, step in enumerate(steps) if line in step]
    assert len(found) == 1, f"{line!r} is in {len(found)} steps"
    return found[0]


def test_windows_tests_the_collected_binaries_before_the_upload():
    collect, _ = _spec_names()
    installer = (ROOT / "installer.iss").read_text(encoding="utf-8")
    assert f'Source: "dist\\{collect}\\*"' in installer
    steps = _steps("build-windows")
    test = _index(steps, TEST_STEP)
    assert _index(steps, "run: python build.py --installer") < test < _index(steps, "- name: Upload Artifacts")
    assert f"EXPECT_FFMPEG_DIR: dist/{collect}/_internal/bin\n" in steps[test]
    assert TEST_RUN in steps[test]


def test_macos_tests_the_signed_binaries_before_the_dmg():
    _, bundle = _spec_names()
    steps = _steps("build-macos")
    test = _index(steps, TEST_STEP)
    assert _index(steps, "- name: Codesign .app") < test < _index(steps, "- name: Build DMG")
    assert f'APP="dist/{bundle}"' in steps[_index(steps, "- name: Codesign .app")]
    assert f"EXPECT_FFMPEG_DIR: dist/{bundle}/Contents/Frameworks/bin\n" in steps[test]
    assert TEST_RUN in steps[test]
    assert "if:" not in steps[test]


def test_workflow_token_is_read_only_by_default():
    text = (ROOT / ".github/workflows/release.yaml").read_text(encoding="utf-8")
    header = text.split("\njobs:\n", 1)[0]
    assert re.search(r"^permissions:\n  contents: read\n", header, re.M)
    writers = [job for job, body in _jobs().items() if re.search(r"^\s+\w[\w-]*: write$", body, re.M)]
    assert writers == ["create-release"]


def test_update_signing_key_job_holds_no_write_token_or_unpinned_package():
    jobs = _jobs()
    (signer,) = [job for job, body in jobs.items() if "secrets.UPDATE_SIGNING_KEY" in body]
    body = jobs[signer]
    assert re.search(r"^    permissions:\n      contents: read\n", body, re.M)
    assert "write" not in body
    checkouts = body.count("uses: actions/checkout@")
    assert checkouts == body.count("persist-credentials: false") == 1
    assert "cache:" not in body
    installs = re.findall(r"pip install[^\n]*", body)
    assert installs and all("--no-deps" in line and "--only-binary :all:" in line for line in installs)
    assert all(" -e " not in line and "--upgrade" not in line for line in installs)


def test_release_job_runs_no_python_and_holds_no_signing_key():
    body = _jobs()["create-release"]
    assert "softprops/action-gh-release@" in body
    assert "secrets." not in body
    assert "actions/checkout@" not in body
    assert "pip " not in body and "python" not in body
