from media_ops_contracts.resolve_approval_signing_key import resolve_approval_signing_key


def test_a_configured_key_is_used_as_is():
    assert resolve_approval_signing_key("shared-secret") == b"shared-secret"


def test_an_unset_key_is_one_random_key_for_the_whole_process():
    first, second = resolve_approval_signing_key(""), resolve_approval_signing_key("")
    assert first == second
    assert len(first) == 32
