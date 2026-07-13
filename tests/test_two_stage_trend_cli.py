from mns.__main__ import build_parser


def test_two_stage_quality_thresholds_are_cli_adjustable():
    args = build_parser().parse_args(
        [
            "run-two-stage-trend-backtest",
            "--start", "2024-01-01",
            "--end", "2026-01-01",
            "--entry-volume-ratio-max", "2.5",
            "--entry-breakout-pct-max", "0.02",
        ]
    )

    assert args.entry_volume_ratio_max == 2.5
    assert args.entry_breakout_pct_max == 0.02


def test_two_stage_ma20_exit_mode_is_cli_adjustable():
    args = build_parser().parse_args(
        [
            "run-two-stage-trend-backtest",
            "--start", "2024-01-01",
            "--end", "2026-01-01",
            "--ma20-exit-mode", "profit_only",
        ]
    )

    assert args.ma20_exit_mode == "profit_only"
