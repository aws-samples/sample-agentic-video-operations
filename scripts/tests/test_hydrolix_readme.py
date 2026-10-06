"""Keep deploy-only Hydrolix configuration out of the offline first run."""

from pathlib import Path

README = (Path(__file__).resolve().parents[2] / "samples" / "hydrolix" / "README.md").read_text()


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
