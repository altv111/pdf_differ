from compare_extractors import build_config


class Args:
    mode = "numeric-primary"
    header_pattern = ["^header$"]
    footer_pattern = ["^footer$"]


def test_build_config_maps_cli_args() -> None:
    cfg = build_config(Args())
    assert cfg.use_numeric_as_primary is True
    assert cfg.header_patterns == ["^header$"]
    assert cfg.footer_patterns == ["^footer$"]
