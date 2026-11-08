from hookline.cli import build_parser, parse_episodes


def test_parse_episodes():
    assert parse_episodes("1-3,7") == [1, 2, 3, 7]
    assert parse_episodes(None) is None


def test_parser_accepts_model_swap_flags():
    args = build_parser().parse_args(["run", "--input", "d", "--out", "o", "--provider", "openai",
                                      "--model", "gpt-x", "--base-url", "http://h/v1"])
    assert (args.provider, args.model, args.base_url) == ("openai", "gpt-x", "http://h/v1")
