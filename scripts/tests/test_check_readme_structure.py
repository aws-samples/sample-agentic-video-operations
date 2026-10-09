from check_readme_structure import REQUIRED_HEADINGS, find_heading_problems


def readme_with(*headings: str) -> str:
    return "\n".join(f"## {heading}" for heading in headings)


def test_required_headings_pass_in_order():
    assert find_heading_problems(readme_with(*REQUIRED_HEADINGS)) == []


def test_missing_and_out_of_order_headings_are_reported():
    text = readme_with("Architecture", "Purpose")
    problems = find_heading_problems(text)
    assert "missing heading: ## Prerequisites" in problems
    assert "headings out of order: ['Architecture', 'Purpose']" in problems
