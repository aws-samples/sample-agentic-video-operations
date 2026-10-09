"""Keep deploy-only Hydrolix configuration out of the offline first run."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "samples" / "hydrolix" / "README.md").read_text()
JUSTFILE = (ROOT / "justfile").read_text()
HYDROLIX_TEST_NAMES = {
    "test_hydrolix_bound_model_sql.py",
    "test_hydrolix_caller_identity.py",
    "test_hydrolix_chart_formatters.py",
    "test_hydrolix_readme.py",
    "test_hydrolix_results_per_user.py",
    "test_hydrolix_web_app.py",
    "test_invoke_hydrolix.py",
    "test_manage_hydrolix_stack.py",
}


def test_local_synth_needs_no_deployment_configuration():
    local_run = README.split("### Run Locally", 1)[1].split("### Deploy to AWS", 1)[0]

    assert "source .env" not in local_run
    assert "--parameters" not in local_run
    assert "HYDROLIX_TABLE" not in local_run
    assert "npx cdk synth CdkHydrolixDataAssistantAgentcoreStrandsStack" in local_run


def test_deploy_path_names_the_required_hydrolix_table():
    deploy = README.split("### Deploy to AWS", 1)[1].split("### Verify the Deployment", 1)[0]

    assert "cp .env.example .env" in deploy
    assert "HYDROLIX_TABLE=your_database.your_table" in deploy


def test_sample_route_runs_every_hydrolix_test_file():
    discovered = {path.name for path in (ROOT / "scripts" / "tests").glob("test_*hydrolix*.py")}

    assert discovered == HYDROLIX_TEST_NAMES
    assert "uv run pytest scripts/tests/test_*hydrolix*.py" in JUSTFILE
    assert "uv run pytest scripts/tests/test_*hydrolix*.py" in README
