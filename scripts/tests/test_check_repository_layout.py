import check_repository_layout as layout
import pytest


def problems(*paths):
    return layout.find_layout_problems(paths)


def test_the_target_layout_passes():
    assert (
        problems(
            "README.md",
            "justfile",
            ".github/workflows/ci.yml",
            "docs/images/architecture.png",
            "samples/cmcd/README.md",
            "samples/hydrolix/docs/images/demo.gif",
            "samples/hydrolix/web/package.json",
            "samples/hydrolix/web/public/index.html",
            "samples/hydrolix/web/public/images/logo.png",
            "samples/hydrolix/web/src/logo.svg",
            "packages/media_ops_contracts/pyproject.toml",
            "fixtures/input_loss/medialive.describe_channel.json",
            "docs/build_a_sample.md",
            ".claude/CLAUDE.md",
        )
        == []
    )


def test_an_unknown_root_entry_fails():
    assert problems("notes/todo.md") == ["root entry not allowed: notes"]


@pytest.mark.parametrize(
    "image",
    [
        "docs/architecture.png",
        "samples/cmcd/docs/flow.svg",
        "samples/cmcd/logo.jpg",
        "samples/cmcd/images/flow.png",
        "samples/medialive/src/medialive_mcp/diagram.PNG",
    ],
)
def test_image_files_outside_docs_images_fail_by_extension(image):
    assert problems(image) == [f"image outside docs/images/ or a web app: {image}"]


def test_a_cdk_app_is_not_a_web_app_so_its_images_fail():
    image = "samples/hub/cdk/assets/icon.png"
    assert problems("samples/hub/cdk/package.json", image) == [
        f"image outside docs/images/ or a web app: {image}"
    ]


def test_a_tracked_plan_file_fails():
    [problem] = problems(".claude/plans/handoff/step-1.md")
    assert problem.startswith("tracked plan file")
