from app.auth import check_password, hash_password


def test_right_password_is_accepted():
    stored = hash_password("test-password-1")
    assert check_password("test-password-1", stored)
