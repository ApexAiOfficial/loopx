from __future__ import annotations

import pytest

from loopx.repository_identity import normalize_repository_identity


@pytest.mark.parametrize(
    "remote",
    [
        "http://code.example.com:80/team/repo.git",
        "https://code.example.com:443/team/repo.git",
        "ssh://git@code.example.com:22/team/repo.git",
        "git://code.example.com:9418/team/repo.git",
        "http://code.example.com/team/repo.git",
        "https://code.example.com/team/repo.git",
        "ssh://git@code.example.com/team/repo.git",
        "git://code.example.com/team/repo.git",
        "git@code.example.com:team/repo.git",
        "git:code.example.com/team/repo",
    ],
)
def test_default_transport_ports_share_repository_identity(remote: str) -> None:
    assert normalize_repository_identity(remote) == "git:code.example.com/team/repo"


@pytest.mark.parametrize(
    ("remote", "expected"),
    [
        ("ssh://git@code.example.com:443/team/repo.git", "git:code.example.com:443/team/repo"),
        ("https://code.example.com:22/team/repo.git", "git:code.example.com:22/team/repo"),
        ("git://code.example.com:80/team/repo.git", "git:code.example.com:80/team/repo"),
        ("http://code.example.com:443/team/repo.git", "git:code.example.com:443/team/repo"),
        ("https://code.example.com:8443/team/repo.git", "git:code.example.com:8443/team/repo"),
        ("ssh://git@code.example.com:2222/team/repo.git", "git:code.example.com:2222/team/repo"),
        ("git://code.example.com:0/team/repo.git", "git:code.example.com:0/team/repo"),
        ("git:code.example.com:443/team/repo", "git:code.example.com:443/team/repo"),
        ("git:code.example.com:9418/team/repo", "git:code.example.com:9418/team/repo"),
    ],
)
def test_nondefault_or_canonical_ports_remain_explicit(remote: str, expected: str) -> None:
    identity = normalize_repository_identity(remote)
    assert identity == expected
    assert normalize_repository_identity(identity) == expected


@pytest.mark.parametrize("port", ["invalid", "-1", "65536"])
def test_invalid_url_ports_are_rejected(port: str) -> None:
    with pytest.raises(ValueError, match="invalid port"):
        normalize_repository_identity(f"ssh://git@code.example.com:{port}/team/repo.git")
