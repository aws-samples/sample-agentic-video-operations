from confirm_aws_action import ConfirmationPrompt, ask_to_continue

PROMPT = ConfirmationPrompt("deploy", "stack", "us-east-1", "111122223333", {"bucket": "b"})


def test_yes_skips_the_question(capsys):
    assert ask_to_continue(PROMPT, assume_yes=True, ask=lambda _: "n")
    assert "bucket: b" in capsys.readouterr().out


def test_only_an_explicit_y_continues():
    assert ask_to_continue(PROMPT, assume_yes=False, ask=lambda _: " Y ")
    assert not ask_to_continue(PROMPT, assume_yes=False, ask=lambda _: "")
    assert not ask_to_continue(PROMPT, assume_yes=False, ask=lambda _: "yes please")


def test_without_a_terminal_it_refuses_without_asking(capsys):
    """T59: nobody can answer, so a later tool must not be left to block or abort."""
    import confirm_aws_action

    asked = []
    prompt = confirm_aws_action.ConfirmationPrompt("deploy", "Stack", "us-west-2", "111122223333")

    confirmed = confirm_aws_action.ask_to_continue(
        prompt, assume_yes=False, ask=asked.append, interactive=False
    )

    assert confirmed is False and asked == []
    assert confirm_aws_action.NO_TERMINAL in capsys.readouterr().out
