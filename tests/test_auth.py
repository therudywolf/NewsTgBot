"""Tests for admin authentication helpers."""

from auth import hash_password, verify_password


def test_password_hash_roundtrip():
    password = "correct horse battery staple"
    password_hash = hash_password(password)

    assert password_hash != password
    assert verify_password(password, password_hash) is True
    assert verify_password("wrong password", password_hash) is False
