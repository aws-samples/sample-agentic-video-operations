"""Published docs may only name commands, interfaces, and paths that exist."""

from pathlib import Path

import check_docs_claims as claims
from validate_documented_commands import ScriptInterface
from validate_documented_surfaces import read_tool_names

JUSTFILE = """
demo:
    uv run demo-agentic-iops-streaming

eval:
    @just _pending_eval

smoke target="":
    case "{{ target }}" in
      "") echo smoke ;;
      aws) echo smoke aws ;;
      *) exit 1 ;;
    esac

deploy sample *flags:
    #!/usr/bin/env bash
    case "{{ sample }}" in
      agentic-iops-streaming) uv run python scripts/manage_agentic_iops_streaming_stack.py deploy ;;
      medialive|mediaconnect) echo "deploys through agentic-iops-streaming" >&2; exit 1 ;;
      langchain) just _pending "{{ sample }}" ;;
      *) just _unknown "{{ sample }}" ;;
    esac
"""
RECIPES = claims.read_recipes(JUSTFILE)
SOURCES = claims.collect_claim_sources(claims.ROOT)


def problems(text):
    return claims.find_problems(Path("README.md"), text, RECIPES, SOURCES)


def sources(
    *,
    tracked: frozenset[str] = frozenset(),
    project_scripts: dict[str, frozenset[str]] | None = None,
    script_interfaces: dict[str, ScriptInterface] | None = None,
    settings: frozenset[str] = frozenset(),
    tools: frozenset[str] = frozenset(),
    outputs: frozenset[str] = frozenset(),
    parameters: frozenset[str] = frozenset(),
) -> claims.ClaimSources:
    return claims.ClaimSources(
        tracked=tracked,
        project_scripts=project_scripts or {},
        script_interfaces=script_interfaces or {},
        settings=settings,
        tools=tools,
        outputs=outputs,
        parameters=parameters,
    )


def test_existing_recipes_and_handled_samples_pass():
    assert problems("Run `just demo`, then `just deploy agentic-iops-streaming`.") == []


def test_a_missing_recipe_fails():
    assert problems("`just demo-channel delete`") == [
        "README.md: `just demo-channel` is not a recipe"
    ]


def test_a_placeholder_recipe_fails():
    assert problems("```bash\njust eval\n```") == ["README.md: `just eval` is only a placeholder"]


def test_an_unimplemented_or_redirected_sample_fails():
    assert problems("`just deploy langchain`") == [
        "README.md: `just deploy langchain` is not implemented"
    ]  # noqa: E501
    assert problems("`just deploy medialive`") == [
        "README.md: `just deploy medialive` is not implemented"
    ]  # noqa: E501


def test_arguments_of_other_just_recipes_are_checked():
    assert problems("`just smoke someday`") == [
        "README.md: `just smoke someday` is not implemented"
    ]


def test_just_arguments_forwarded_to_scripts_are_checked():
    justfile = """
doctor group="":
    uv run python scripts/check_prerequisites.py {{ group }}

deploy sample *flags:
    case "{{ sample }}" in
      cmcd) uv run python scripts/manage_cmcd_stack.py deploy {{ flags }} ;;
      *) just _unknown "{{ sample }}" ;;
    esac
"""
    recipes = claims.read_recipes(justfile)
    interfaces = {
        "scripts/check_prerequisites.py": ScriptInterface((frozenset({"aws"}),), ()),
        "scripts/manage_cmcd_stack.py": ScriptInterface(
            (frozenset({"deploy"}),), (("--yes", False),)
        ),
    }
    found = claims.find_problems(
        Path("README.md"),
        "`just doctor nowhere` and `just deploy cmcd --no-such-flag`",
        recipes,
        sources(script_interfaces=interfaces),
    )
    assert found == [
        "README.md: scripts/check_prerequisites.py has no 'nowhere' subcommand",
        "README.md: scripts/manage_cmcd_stack.py has no --no-such-flag flag",
    ]


def test_a_missing_repository_path_fails_and_templates_are_skipped():
    assert problems("see `samples/nowhere/cdk`") == [
        "README.md: samples/nowhere/cdk does not exist"
    ]
    assert problems("see `samples/<key>/README.md`") == []


def test_a_missing_templated_repository_path_fails():
    assert problems("see `samples/<key>/tests/nowhere/test_<key>.py`") == [
        "README.md: samples/<key>/tests/nowhere/test_<key>.py does not exist"
    ]


def test_a_templated_path_placeholder_cannot_cross_a_directory():
    tracked = frozenset(
        {
            "samples",
            "samples/agentic-iops-streaming",
            "samples/agentic-iops-streaming/cdk",
            "samples/agentic-iops-streaming/cdk/README.md",
        }
    )
    found = claims.find_problems(
        Path("README.md"),
        "see `samples/<key>/README.md`",
        RECIPES,
        sources(tracked=tracked),
    )
    assert found == ["README.md: samples/<key>/README.md does not exist"]


def test_a_missing_sample_relative_path_fails():
    tracked = frozenset({"samples", "samples/medialive", "samples/medialive/README.md"})
    found = claims.find_problems(
        Path("samples/medialive/README.md"),
        "see `tool_surface/create_missing_tools.py`",
        RECIPES,
        sources(tracked=tracked),
    )
    assert found == [
        "samples/medialive/README.md: tool_surface/create_missing_tools.py "
        "does not exist under samples/medialive"
    ]


def test_an_unprefixed_sample_relative_file_is_checked():
    tracked = frozenset(
        {"samples", "samples/agentic-iops-streaming", "samples/agentic-iops-streaming/README.md"}
    )
    found = claims.find_problems(
        Path("samples/agentic-iops-streaming/README.md"),
        "Load `demo-channel.json`.",
        RECIPES,
        sources(tracked=tracked),
    )
    assert found == [
        "samples/agentic-iops-streaming/README.md: demo-channel.json does not exist under "
        "samples/agentic-iops-streaming"
    ]


def test_a_sample_relative_file_cannot_be_satisfied_by_another_package():
    tracked = frozenset(
        {
            "samples",
            "samples/agentic-iops-streaming",
            "samples/agentic-iops-streaming/README.md",
            "samples/cmcd/cloudfront-cmcd-kinesis.yaml",
            "packages/media_ops_contracts/tests/test_domain_pack.py",
        }
    )
    found = claims.find_problems(
        Path("samples/agentic-iops-streaming/README.md"),
        "Edit `cloudfront-cmcd-kinesis.yaml` and `test_domain_pack.py`.",
        RECIPES,
        sources(tracked=tracked),
    )
    assert found == [
        "samples/agentic-iops-streaming/README.md: cloudfront-cmcd-kinesis.yaml does not exist "
        "under samples/agentic-iops-streaming",
        "samples/agentic-iops-streaming/README.md: test_domain_pack.py does not exist under "
        "samples/agentic-iops-streaming",
    ]


def test_a_package_relative_file_in_docs_is_checked():
    tracked = frozenset(
        {
            "packages",
            "packages/media_ops_contracts",
            "packages/media_ops_contracts/src",
            "packages/media_ops_contracts/src/media_ops_contracts",
        }
    )
    found = claims.find_problems(
        Path("docs/extend_agentic_iops_streaming.md"),
        "See `media_ops_contracts/no_such_module.py`.",
        RECIPES,
        sources(tracked=tracked),
    )
    assert found == [
        "docs/extend_agentic_iops_streaming.md: package path "
        "media_ops_contracts/no_such_module.py does not exist"
    ]


def test_the_real_justfile_parses():
    recipes = claims.read_recipes((claims.ROOT / "justfile").read_text())
    assert {"demo", "deploy", "destroy", "docs-check"} <= set(recipes)
    assert "agentic-iops-streaming" in claims.handled_samples(recipes["deploy"])


def test_a_script_subcommand_and_flag_must_exist():
    interfaces = {
        "scripts/manage_agentic_iops_streaming_stack.py": ScriptInterface(
            (frozenset({"deploy", "destroy"}),), (("--yes", False),)
        )
    }
    text = "`uv run python scripts/manage_agentic_iops_streaming_stack.py launch --force`"
    found = claims.find_problems(
        Path("README.md"),
        text,
        RECIPES,
        sources(script_interfaces=interfaces),
    )
    assert (
        "README.md: scripts/manage_agentic_iops_streaming_stack.py has no 'launch' subcommand"
        in found
    )
    assert "README.md: scripts/manage_agentic_iops_streaming_stack.py has no --force flag" in found


def test_a_uv_package_script_must_be_declared():
    found = claims.find_problems(
        Path("README.md"),
        "`uv run --package agentic-iops-streaming demo-later`",
        RECIPES,
        sources(
            project_scripts={"agentic-iops-streaming": frozenset({"demo-agentic-iops-streaming"})}
        ),
    )
    assert found == [
        "README.md: 'demo-later' is not a script of uv package 'agentic-iops-streaming'",
    ]


def test_uv_options_between_package_and_script_are_skipped():
    found = claims.find_problems(
        Path("README.md"),
        "`uv run --package agentic-iops-streaming --env-file .env serve-agentic-iops-streaming`",
        RECIPES,
        sources(
            project_scripts={"agentic-iops-streaming": frozenset({"serve-agentic-iops-streaming"})}
        ),
    )
    assert found == []


def test_an_environment_setting_must_be_declared():
    found = claims.find_problems(
        Path("README.md"),
        "| Setting | Default |\n|---|---|\n| `RETIRED_MODEL_ID` | empty |",
        RECIPES,
        sources(settings=frozenset({"AGENT_MODEL_ID"})),
    )
    assert found == ["README.md: RETIRED_MODEL_ID is not a declared environment setting"]


def test_environment_assignments_in_prose_and_dotenv_blocks_must_be_declared():
    text = (
        "Set `AGENTIC_IOPS_NOT_A_SETTING=true` in `.env`.\n\n"
        "```dotenv\nALSO_NOT_A_SETTING=value\nAGENT_MODEL_ID=value\n```"
    )
    found = claims.find_problems(
        Path("README.md"),
        text,
        RECIPES,
        sources(settings=frozenset({"AGENT_MODEL_ID"})),
    )
    assert set(found) == {
        "README.md: AGENTIC_IOPS_NOT_A_SETTING is not a declared environment setting",
        "README.md: ALSO_NOT_A_SETTING is not a declared environment setting",
    }


def test_an_available_tool_must_be_registered():
    found = claims.find_problems(
        Path("README.md"),
        "## Available Tools\n\n| Tool | Mode |\n|---|---|\n| `restart_encoder` | Write |",
        RECIPES,
        sources(tools=frozenset({"stop_channel"})),
    )
    assert found == ["README.md: 'restart_encoder' is not a registered tool"]


def test_tools_in_skills_and_expected_results_must_be_registered():
    skill = claims.find_problems(
        Path("samples/medialive/src/medialive_mcp/skills/read-health/SKILL.md"),
        "1. Call `restart_encoder(channel_id)` once.",
        RECIPES,
        sources(tools=frozenset({"check_channel_issues"})),
    )
    expected = claims.find_problems(
        Path("samples/medialive/README.md"),
        "Expected result: the assistant calls `restart_encoder` once.",
        RECIPES,
        sources(tools=frozenset({"check_channel_issues"})),
    )
    assert skill == [
        "samples/medialive/src/medialive_mcp/skills/read-health/SKILL.md: "
        "'restart_encoder' is not a registered tool"
    ]
    assert expected == ["samples/medialive/README.md: 'restart_encoder' is not a registered tool"]


def test_the_coordinator_workflow_tools_are_registered():
    tools = read_tool_names(claims.ROOT)

    assert {"discover_workflow", "save_workflow", "list_workflows", "get_workflow"} <= tools


def test_discover_and_save_tools_named_in_a_skill_must_be_registered():
    found = claims.find_problems(
        Path("samples/agentic-iops-streaming/src/agentic_iops_streaming/skills/map/SKILL.md"),
        "1. Call `discover_topology(arn)`, then `save_topology(topology_id)`.",
        RECIPES,
        sources(tools=frozenset({"discover_workflow", "save_workflow"})),
    )

    assert found == [
        "samples/agentic-iops-streaming/src/agentic_iops_streaming/skills/map/SKILL.md: "
        f"{name!r} is not a registered tool"
        for name in ("discover_topology", "save_topology")
    ]


def test_stack_outputs_and_cdk_parameters_must_be_declared():
    text = (
        "Read the `NoSuchOutputName` stack output.\n"
        "Run `cdk deploy --parameters NoSuchParameter=x`."
    )
    found = claims.find_problems(
        Path("README.md"),
        text,
        RECIPES,
        sources(outputs=frozenset({"AgentRuntimeArn"}), parameters=frozenset({"BedrockModelId"})),
    )
    assert found == [
        "README.md: 'NoSuchOutputName' is not a declared stack output",
        "README.md: 'NoSuchParameter' is not a declared CDK parameter",
    ]


def test_stack_names_and_context_values_are_not_infrastructure_names():
    text = (
        "The `AgenticIopsStreamingStack` stack output `AgentRuntimeArn` identifies the runtime.\n"
        "`npx cdk deploy AgenticIopsStreamingStack --parameters BedrockModelId=x "
        "-c writeTag=MediaOpsManaged=true`"
    )
    found = claims.find_problems(
        Path("README.md"),
        text,
        RECIPES,
        sources(outputs=frozenset({"AgentRuntimeArn"}), parameters=frozenset({"BedrockModelId"})),
    )
    assert found == []


def test_only_names_after_parameters_until_the_next_option_are_checked():
    text = (
        "`npx cdk deploy AgenticIopsStreamingStack --parameters NoSuchParameter=x "
        "-c writeTag=MediaOpsManaged=true`"
    )
    found = claims.find_problems(
        Path("README.md"),
        text,
        RECIPES,
        sources(parameters=frozenset({"BedrockModelId"})),
    )
    assert found == ["README.md: 'NoSuchParameter' is not a declared CDK parameter"]


def test_markdown_link_anchors_must_exist(tmp_path, monkeypatch):
    target = tmp_path / "target.md"
    target.write_text("# Real Section\n")
    monkeypatch.setattr(claims, "ROOT", tmp_path)
    tracked = frozenset({"README.md", "target.md"})
    found = claims.find_problems(
        Path("README.md"),
        "[see](target.md#no-such-section)",
        RECIPES,
        sources(tracked=tracked),
    )
    assert found == ["README.md: link anchor target.md#no-such-section does not exist"]


def test_an_untracked_local_file_does_not_satisfy_a_path_claim():
    tracked = frozenset(
        {"samples", "samples/agentic-iops-streaming", "samples/agentic-iops-streaming/README.md"}
    )
    text = (
        "see `samples/agentic-iops-streaming/README.md` and "
        "`samples/agentic-iops-streaming/cdk/node_modules/.bin/cdk`"
    )
    assert claims.find_problems(Path("README.md"), text, RECIPES, sources(tracked=tracked)) == [
        "README.md: samples/agentic-iops-streaming/cdk/node_modules/.bin/cdk does not exist"
    ]


def test_plan_language_presented_as_product_state_fails():
    text = (
        "The runtime has not landed.\nNo own deploy after step 4.\n"
        "This is not implemented.\nIt arrives later.\nThe future runtime differs.\n"
        "It is not ready yet.\nFollow step 5 of Run Locally."
    )
    found = problems(text)
    assert "README.md:1: plan language as product state: 'has not landed'" in found
    assert "README.md:2: plan language as product state: 'after step 4'" in found
    assert "README.md:3: plan language as product state: 'not implemented'" in found
    assert any(problem.startswith("README.md:4:") and "later" in problem for problem in found)
    assert any(problem.startswith("README.md:5:") and "future" in problem for problem in found)
    assert any(problem.startswith("README.md:6:") and "yet" in problem for problem in found)
    assert len(found) == 6  # a numbered instruction step is not plan language


def test_incremental_later_and_when_lands_plan_language_fails():
    text = (
        "Fixture coverage is being added incrementally.\n"
        "MediaConnect now, cmcd later.\n"
        "When the agentic-iops-streaming deployment lands, verify it.\n"
        "A session id reused later reaches its own history.\n"
        "Use CTA-5004 or later."
    )
    found = problems(text)
    assert len(found) == 3
    assert "being added" in found[0]
    assert "cmcd later" in found[1]
    assert "When the agentic-iops-streaming deployment lands" in found[2]


def test_common_future_plan_phrases_fail():
    text = (
        "Thumbnail support comes later.\n"
        "A CMCD pack will be added.\n"
        "The Hydrolix pack is coming soon.\n"
        "A cmcd domain pack is planned.\n"
        "TODO: document the teardown."
    )
    found = problems(text)
    assert len(found) == 5
    for phrase in ("comes later", "will be added", "is coming soon", "is planned", "TODO:"):
        assert any(phrase.lower() in problem.lower() for problem in found)


def test_a_conditional_not_yet_deployed_instruction_passes():
    assert (
        problems("If the stack is not yet deployed, run `just deploy agentic-iops-streaming`.")
        == []
    )


def test_justfile_messages_cannot_advertise_future_state():
    assert claims.find_justfile_problems(
        'demo:\n    @echo "The demo is not implemented yet."\n'
    ) == [
        "justfile:2: plan language as product state: 'is not implemented yet'",
    ]


def test_main_runs_the_justfile_plan_language_check(tmp_path, monkeypatch):
    (tmp_path / "justfile").write_text('demo:\n    @echo "The demo is not implemented yet."\n')
    monkeypatch.setattr(claims, "ROOT", tmp_path)
    monkeypatch.setattr(claims, "tracked_docs", lambda: [])
    monkeypatch.setattr(claims, "collect_claim_sources", lambda root: sources())
    assert claims.main() == 1


def test_tracked_docs_include_only_the_public_claude_instructions():
    docs = {path.relative_to(claims.ROOT).as_posix() for path in claims.tracked_docs()}

    assert ".claude/CLAUDE.md" in docs
    assert not any(path.startswith(".claude/") and path != ".claude/CLAUDE.md" for path in docs)


def test_a_false_claim_in_claude_instructions_fails():
    assert claims.find_problems(
        Path(".claude/CLAUDE.md"),
        "Run `just imaginary-gate`.",
        RECIPES,
    ) == [".claude/CLAUDE.md: `just imaginary-gate` is not a recipe"]
