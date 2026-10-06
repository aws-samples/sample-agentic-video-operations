"""Validate documented environment settings and MCP tool names."""

import ast
import re
import shlex
from pathlib import Path

ENV_TABLE_ROW = re.compile(r"^\|\s*`([A-Z][A-Z0-9_]*)`\s*\|", re.MULTILINE)
ENV_SETTING = re.compile(r"`([A-Z][A-Z0-9_]*)`\s+(?:environment variable|setting)\b")
ENV_ASSIGNMENT = re.compile(r"`([A-Z][A-Z0-9_]*)=[^`\n]*`")
DOTENV_ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)=", re.MULTILINE)
ENV_READ = re.compile(
    r"os\.(?:getenv|environ\.get)\(\s*['\"]([A-Z][A-Z0-9_]*)['\"]"
    r"|os\.environ\[\s*['\"]([A-Z][A-Z0-9_]*)['\"]\s*\]"
)
FENCE = re.compile(r"^```([a-z0-9_-]*)\s*$")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$")
TOOL_NAME = re.compile(r"`([a-z][a-z0-9_]+)`")
TOOL_CALL = re.compile(r"`([a-z][a-z0-9_]+)\s*\(")
INFRASTRUCTURE_NAME = re.compile(r"`([A-Z][A-Za-z0-9]+)(?:=[^`]*)?`")
INFRASTRUCTURE_NAME_PATTERN = r"`[A-Z][A-Za-z0-9]+(?:=[^`]*)?`"
STACK_OUTPUT = re.compile(r"\bstack (output|outputs)\b", re.IGNORECASE)
OUTPUT_KEY = re.compile(r"\bOutputKey\s*==?\s*[`'\"]?([A-Z][A-Za-z0-9]+)")
CDK_PARAMETER = re.compile(r"(?:[^:=\s]+:)?([A-Z][A-Za-z0-9]+)=")
CDK_DECLARATION = re.compile(
    r"new\s+(?:cdk\.)?Cfn(?P<kind>Output|Parameter)"
    r"\s*\(\s*[^,]+,\s*['\"](?P<name>[A-Za-z][A-Za-z0-9]*)['\"]"
)
TOOL_FACTORIES = {
    "build_cmcd_server",
    "create_load_skill_tool",
    "create_read_tools",
    "create_write_tools",
}
TOOL_ACTION = re.compile(
    r"(?:analyze|check|create|delete|describe|get|identify|list|load|read|restart|"
    r"start|stop|switch)_[a-z0-9_]+"
)


def read_setting_names(root: Path) -> frozenset[str]:
    """Return BaseSettings fields plus root environment-template keys."""
    names = set()
    for path in root.glob("samples/**/settings/runtime_settings.py"):
        if "cdk.out" in path.parts:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or not _inherits_base_settings(node):
                continue
            names.update(
                item.target.id.upper()
                for item in node.body
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
            )
    env_example = root / ".env.example"
    if env_example.exists():
        names.update(
            match.group(1)
            for line in env_example.read_text().splitlines()
            if (match := re.match(r"^#?\s*([A-Z][A-Z0-9_]*)=", line))
        )
    for path in (*root.glob("scripts/**/*.py"), *root.glob("samples/**/*.py")):
        if any(part in {"cdk.out", "node_modules"} for part in path.parts):
            continue
        for match in ENV_READ.finditer(path.read_text()):
            names.add(match.group(1) or match.group(2))
    return frozenset(names)


def read_tool_names(root: Path) -> frozenset[str]:
    """Return tool names from factories, decorators, and dynamic action names."""
    names = set()
    for path in root.glob("samples/**/src/**/*.py"):
        if any(part in {"cdk.out", "node_modules", "tests"} for part in path.parts):
            continue
        source = path.read_text()
        tree = ast.parse(source, filename=str(path))
        names.update(_dynamic_tool_names(tree))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                if _is_tool_function(node):
                    names.add(_decorated_tool_name(node))
                if _inside_tool_factory(node, tree):
                    names.add(node.name)
    return frozenset(names)


def read_infrastructure_names(root: Path) -> tuple[frozenset[str], frozenset[str]]:
    """Return declared CloudFormation output and parameter logical names."""
    outputs: set[str] = set()
    parameters: set[str] = set()
    for path in root.glob("samples/**/*"):
        if not path.is_file() or any(part in {"cdk.out", "node_modules"} for part in path.parts):
            continue
        if path.suffix == ".ts":
            for match in CDK_DECLARATION.finditer(path.read_text()):
                target = outputs if match.group("kind") == "Output" else parameters
                target.add(match.group("name"))
        elif path.suffix in {".yaml", ".yml"}:
            yaml_outputs, yaml_parameters = _read_yaml_sections(path.read_text())
            outputs.update(yaml_outputs)
            parameters.update(yaml_parameters)
    return frozenset(outputs), frozenset(parameters)


def find_surface_problems(
    doc: Path,
    text: str,
    settings: frozenset[str],
    tools: frozenset[str],
    outputs: frozenset[str] = frozenset(),
    parameters: frozenset[str] = frozenset(),
) -> list[str]:
    """Return documented settings, tools and infrastructure names absent from code."""
    environment_names = {
        *ENV_TABLE_ROW.findall(text),
        *ENV_SETTING.findall(text),
        *ENV_ASSIGNMENT.findall(text),
        *_dotenv_names(text),
    }
    problems = [
        f"{doc}: {name} is not a declared environment setting"
        for name in environment_names
        if name not in settings
    ]
    in_tool_section = False
    in_expected_result = False
    for line in text.splitlines():
        if heading := HEADING.match(line):
            in_tool_section = heading.group(1).strip().lower() == "available tools"
            in_expected_result = False
            continue
        if "expected result" in line.lower():
            in_expected_result = True
        elif in_expected_result and not line.strip():
            in_expected_result = False
        candidates = []
        if in_tool_section and line.startswith("|"):
            candidates.extend(TOOL_NAME.findall(line.split("|", 2)[1]))
        if in_expected_result:
            candidates.extend(TOOL_NAME.findall(line))
        for name in candidates:
            if TOOL_ACTION.fullmatch(name) and name not in tools:
                problems.append(f"{doc}: {name!r} is not a registered tool")
    if doc.name == "SKILL.md":
        for name in TOOL_CALL.findall(text):
            if TOOL_ACTION.fullmatch(name) and name not in tools:
                problems.append(f"{doc}: {name!r} is not a registered tool")
    for name in _stack_output_names(text):
        if name not in outputs:
            problems.append(f"{doc}: {name!r} is not a declared stack output")
    for block in re.findall(r"`([^`\n]+)`|```[^\n]*\n(.*?)```", text, re.DOTALL):
        span = block[0] or block[1]
        for name in _cdk_parameter_names(span):
            if name not in parameters:
                problems.append(f"{doc}: {name!r} is not a declared CDK parameter")
    return problems


def _stack_output_names(text: str) -> set[str]:
    names = set(OUTPUT_KEY.findall(text))
    for line in text.splitlines():
        for phrase in STACK_OUTPUT.finditer(line):
            after = line[phrase.end() :]
            found_after = False
            if sequence := re.match(
                rf"(?:\s+(?:named|is|are))?\s*[:=]?\s*"
                rf"((?:{INFRASTRUCTURE_NAME_PATTERN}(?:\s*(?:,|and)\s*)?)+)",
                after,
                re.IGNORECASE,
            ):
                names.update(INFRASTRUCTURE_NAME.findall(sequence.group(1)))
                found_after = True
            if not found_after:
                before = line[: phrase.start()]
                if sequence := re.search(
                    rf"((?:{INFRASTRUCTURE_NAME_PATTERN}(?:\s*(?:,|and)\s*)?)+)\s*$",
                    before,
                    re.IGNORECASE,
                ):
                    names.update(INFRASTRUCTURE_NAME.findall(sequence.group(1)))
    return names


def _cdk_parameter_names(span: str) -> set[str]:
    if "--parameters" not in span:
        return set()
    try:
        tokens = shlex.split(span)
    except ValueError:
        tokens = span.split()
    names = set()
    reading_parameters = False
    for argument in tokens:
        if argument == "--parameters":
            reading_parameters = True
            continue
        if argument.startswith("--parameters="):
            reading_parameters = True
            argument = argument.partition("=")[2]
        elif reading_parameters and argument.startswith("-"):
            reading_parameters = False
            continue
        if reading_parameters and (match := CDK_PARAMETER.match(argument)):
            names.add(match.group(1))
    return names


def _dotenv_names(text: str) -> set[str]:
    names: set[str] = set()
    language = None
    lines: list[str] = []
    for line in text.splitlines():
        if fence := FENCE.match(line):
            if language is None:
                language = fence.group(1)
                lines = []
            else:
                if language in {"dotenv", "env"}:
                    names.update(DOTENV_ASSIGNMENT.findall("\n".join(lines)))
                language = None
                lines = []
            continue
        if language is not None:
            lines.append(line)
    return names


def _read_yaml_sections(text: str) -> tuple[set[str], set[str]]:
    outputs: set[str] = set()
    parameters: set[str] = set()
    section = None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith((" ", "\t")):
            heading = re.fullmatch(r"(Outputs|Parameters):\s*", line)
            section = heading.group(1) if heading else None
            continue
        if section and (match := re.match(r"^  ([A-Za-z][A-Za-z0-9]*):\s*$", line)):
            target = outputs if section == "Outputs" else parameters
            target.add(match.group(1))
    return outputs, parameters


def _inherits_base_settings(node: ast.ClassDef) -> bool:
    return any(
        (isinstance(base, ast.Name) and base.id == "BaseSettings")
        or (isinstance(base, ast.Attribute) and base.attr == "BaseSettings")
        for base in node.bases
    )


def _is_tool_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.func.attr == "tool"
        for decorator in node.decorator_list
    )


def _decorated_tool_name(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        for keyword in decorator.keywords:
            if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
                return str(keyword.value.value)
    return node.name


def _inside_tool_factory(
    candidate: ast.FunctionDef | ast.AsyncFunctionDef, tree: ast.Module
) -> bool:
    if candidate.name in {"read", "read_all", "check", "channel", "translate_action_result"}:
        return False
    for top_level in tree.body:
        if not isinstance(top_level, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if top_level.name not in TOOL_FACTORIES:
            continue
        if any(candidate is child for child in ast.walk(top_level) if child is not top_level):
            return bool(TOOL_ACTION.fullmatch(candidate.name))
    return False


def _dynamic_tool_names(tree: ast.Module) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.For | ast.comprehension) and _target_names_action(node.target):
            names.update(_string_values(node.iter))
    return {name for name in names if TOOL_ACTION.fullmatch(name)}


def _target_names_action(target: ast.expr) -> bool:
    if isinstance(target, ast.Name):
        return target.id == "action"
    if isinstance(target, ast.Tuple):
        return any(isinstance(item, ast.Name) and item.id == "action" for item in target.elts)
    return False


def _string_values(node: ast.expr) -> set[str]:
    values = set()
    for item in node.elts if isinstance(node, ast.List | ast.Tuple | ast.Set) else [node]:
        if isinstance(item, ast.Constant) and isinstance(item.value, str):
            values.add(item.value)
        elif isinstance(item, ast.Tuple):
            values.update(
                child.value
                for child in item.elts
                if isinstance(child, ast.Constant) and isinstance(child.value, str)
            )
    return values
