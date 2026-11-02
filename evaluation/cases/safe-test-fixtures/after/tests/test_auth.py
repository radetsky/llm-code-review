import pytest

from app.auth import check_password, hash_password

TEST_PASSWORD = "test-password-1"
OTHER_PASSWORD = "test-password-2"


@pytest.fixture
def api_environment(monkeypatch):
    monkeypatch.setenv("API_KEY", "dummy-key-for-tests")
    monkeypatch.setenv("API_URL", "http://localhost:9999")


def test_right_password_is_accepted():
    stored = hash_password(TEST_PASSWORD)
    assert check_password(TEST_PASSWORD, stored)


def test_wrong_password_is_rejected():
    stored = hash_password(TEST_PASSWORD)
    assert not check_password(OTHER_PASSWORD, stored)


def test_same_password_gives_different_hashes():
    assert hash_password(TEST_PASSWORD) != hash_password(TEST_PASSWORD)


def test_environment_is_set(api_environment):
    import os

    assert os.environ["API_KEY"] == "dummy-key-for-tests"
