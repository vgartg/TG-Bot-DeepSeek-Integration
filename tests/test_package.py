import legal_bot


def test_version_is_semver_like():
    parts = legal_bot.__version__.split(".")
    assert len(parts) == 3
    for part in parts:
        assert part.isdigit()


def test_config_module_loads():
    from legal_bot import config

    assert config.CURRENCY == "RUB"
    assert config.PRICES["question_text"] == 20000
    assert config.PRICES["question_file"] == 30000
    assert config.PRICES["subscription_3months"] == 300000
    assert ".pdf" in config.SUPPORTED_FILE_TYPES
    assert ".docx" in config.SUPPORTED_FILE_TYPES
    assert ".txt" in config.SUPPORTED_FILE_TYPES
