from confirm_aws_action import ConfirmationPrompt, ask_to_continue

PROMPT = ConfirmationPrompt("deploy", "stack", "us-east-1", "111122223333", {"bucket": "b"})


def test_yes_skips_the_question(capsys):
    assert ask_to_continue(PROMPT, assume_yes=True, ask=lambda _: "n")
    assert "bucket: b" in capsys.readouterr().out


def test_only_an_explicit_y_continues():
    assert ask_to_continue(PROMPT, assume_yes=False, ask=lambda _: " Y ")
    assert not ask_to_continue(PROMPT, assume_yes=False, ask=lambda _: "")
    assert not ask_to_continue(PROMPT, assume_yes=False, ask=lambda _: "yes please")
