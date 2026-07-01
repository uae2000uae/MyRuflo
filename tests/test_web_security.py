from myruflo.web.security import hash_password, verify_password


def test_round_trip():
    encoded = hash_password("hunter2")
    assert verify_password("hunter2", encoded)


def test_wrong_password_fails():
    encoded = hash_password("hunter2")
    assert not verify_password("wrong", encoded)


def test_same_password_hashes_differently_each_time():
    first = hash_password("hunter2")
    second = hash_password("hunter2")
    assert first != second
    assert verify_password("hunter2", first)
    assert verify_password("hunter2", second)


def test_malformed_hash_fails_closed():
    assert not verify_password("hunter2", "not-a-real-hash")
