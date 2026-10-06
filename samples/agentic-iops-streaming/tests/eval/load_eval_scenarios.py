"""Load every scenario.yaml in stable name order."""

from pathlib import Path

import yaml
from scenario_models import EvalScenario


def load_eval_scenarios(root: Path) -> list[EvalScenario]:
    return [
        EvalScenario.model_validate(yaml.safe_load(path.read_text()))
        for path in sorted(root.glob("*/scenario.yaml"))
    ]
