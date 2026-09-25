from evaluation.environment import capture_environment


def test_captures_expected_shape():
    env = capture_environment("abc123")
    assert env["git_commit"] == "abc123"
    assert isinstance(env["python_version"], str)
    assert isinstance(env["platform"], str)
    assert isinstance(env["cpu_architecture"], str)
    assert isinstance(env["cpu_count"], int) or env["cpu_count"] is None
    assert isinstance(env["package_versions"], dict)


def test_never_includes_excluded_fields():
    env = capture_environment("abc123")
    serialized = str(env).lower()
    for forbidden in (
        "username",
        "home",
        "hostname",
        "mac_address",
        "serial",
        "api_key",
        "token",
        "credential",
        "/users/",
    ):
        assert forbidden not in serialized


def test_package_versions_include_the_pinned_ml_stack():
    env = capture_environment("abc123")
    for package in ("sentence-transformers", "transformers", "torch", "numpy"):
        assert package in env["package_versions"]
        assert env["package_versions"][package] is not None


def test_unknown_package_reports_none_not_a_fabricated_version():
    from evaluation.environment import _package_version

    assert _package_version("this-package-definitely-does-not-exist-xyz") is None
