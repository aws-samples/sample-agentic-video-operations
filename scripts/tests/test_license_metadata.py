import json
import tomllib
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

PYTHON_MANIFESTS = (
    "pyproject.toml",
    "packages/media_ops_contracts/pyproject.toml",
    "packages/media_ops_video_quality/pyproject.toml",
    "samples/cmcd/pyproject.toml",
    "samples/hls-doctor/pyproject.toml",
    "samples/hub/pyproject.toml",
    "samples/mediaconnect/pyproject.toml",
    "samples/medialive/pyproject.toml",
)
JAVASCRIPT_MANIFESTS = (
    "samples/hls-doctor/player-probe/package.json",
    "samples/hub/cdk/package.json",
    "samples/hydrolix/amplify-hydrolix-data-assistant-agentcore-strands/package.json",
    "samples/hydrolix/cdk-hydrolix-data-assistant-agentcore-strands/package.json",
)
CDK_LOCKFILES = (
    "samples/hub/cdk/package-lock.json",
    "samples/hydrolix/cdk-hydrolix-data-assistant-agentcore-strands/package-lock.json",
)


def read_json(path: str) -> dict:
    return json.loads((REPOSITORY_ROOT / path).read_text())


def test_every_python_project_declares_mit_zero():
    for path in PYTHON_MANIFESTS:
        manifest = tomllib.loads((REPOSITORY_ROOT / path).read_text())
        assert manifest["project"]["license"] == "MIT-0", path


def test_every_javascript_project_is_private_and_declares_mit_zero():
    for path in JAVASCRIPT_MANIFESTS:
        manifest = read_json(path)
        assert manifest["private"] is True, path
        assert manifest["license"] == "MIT-0", path
        assert "author" not in manifest, path


def test_cdk_lockfiles_preserve_root_package_metadata():
    for path in CDK_LOCKFILES:
        root_package = read_json(path)["packages"][""]
        assert root_package["private"] is True, path
        assert root_package["license"] == "MIT-0", path


def test_hydrolix_web_has_no_proprietary_rights_footer():
    web_root = (
        REPOSITORY_ROOT
        / "samples"
        / "hydrolix"
        / "amplify-hydrolix-data-assistant-agentcore-strands"
        / "src"
    )
    sources = "\n".join(path.read_text() for path in web_root.rglob("*.js"))

    assert "All rights reserved" not in sources
