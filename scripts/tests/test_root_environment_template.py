from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ROOT_TEMPLATE = REPOSITORY_ROOT / ".env.example"
SAMPLE_SETTINGS = (
    "MEDIA_DOMAINS",
    "AGENTIC_IOPS_TOOL_BUDGET",
    "AGENTIC_IOPS_WRITE_TAG",
    "SESSION_DIR",
    "MEDIALIVE_CHANNEL_ID",
    "MEDIACONNECT_FLOW_ARN",
    "HLS_TIMEOUT_SECONDS",
    "HLS_USER_AGENT",
    "HLS_MAX_WATCH_SECONDS",
    "HLS_ALLOW_PRIVATE_TARGETS",
    "CMCD_ORIGIN_DOMAIN",
    "CMCD_S3_BUCKET_NAME",
    "CMCD_ARTIFACTS_BUCKET",
    "INFLUXDB_URL",
    "INFLUXDB_TOKEN",
    "INFLUXDB_ORG",
    "VERIFY_SSL",
    "HYDROLIX_TABLE",
    "HYDROLIX_AMPLIFY_APP_ID",
    "HYDROLIX_SECRET_ARN",
    "QUESTION_ANSWERS_TABLE",
)


def test_root_template_contains_every_commented_sample_setting():
    lines = ROOT_TEMPLATE.read_text().splitlines()

    for name in SAMPLE_SETTINGS:
        assert any(line.startswith(f"# {name}=") for line in lines), name


def test_sample_folders_have_no_environment_template():
    assert list((REPOSITORY_ROOT / "samples").glob("*/.env.example")) == []
