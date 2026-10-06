import pytest
from check_readme_structure import find_task_ids


@pytest.mark.parametrize(
    "line",
    [
        "`just deploy medialive` arrives with task C3.2.",
        "They move to the new package in task G3.2.",
        "Task R1 moves the folders.",
        "Fixed in C4.1 and G2.3.",
    ],
)
def test_internal_task_ids_are_reported(line):
    assert find_task_ids(line)


@pytest.mark.parametrize(
    "line",
    [
        "Available from step 4c.",
        "Python 3.12 or newer, Node.js 20, H.264 video, 5.1 audio.",
        "Run `just test cmcd`.",
    ],
)
def test_ordinary_text_is_not_reported(line):
    assert find_task_ids(line) == []


def test_the_line_number_is_reported():
    assert find_task_ids("ok\nsee C3.2") == ["internal task id on line 2: C3.2"]
