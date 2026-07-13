from app_module.v3_effectiveness_metrics import compute_effectiveness_metrics


def test_metrics_use_ready_rows_only_and_integer_basis_points() -> None:
    result = compute_effectiveness_metrics(
        [
            {"status": "ready", "score_bp": 9000, "return_bp": 1200, "mae_bp": -300, "mfe_bp": 1500},
            {"status": "ready", "score_bp": 8000, "return_bp": -400, "mae_bp": -900, "mfe_bp": 200},
            {"status": "pending", "score_bp": 10000, "return_bp": 9999},
        ],
        k=2,
    )

    assert result.ready_count == 2
    assert result.precision_at_k_bp == 5000
    assert result.hit_rate_bp == 5000
    assert result.average_gain_bp == 1200
    assert result.average_loss_abs_bp == 400
    assert result.payoff_ratio_bp == 30000
    assert result.mae_mfe_ready is True


def test_score_bucket_returns_report_monotonicity() -> None:
    result = compute_effectiveness_metrics(
        [
            {"status": "ready", "score_bp": 1000, "return_bp": -300},
            {"status": "ready", "score_bp": 2000, "return_bp": 100},
            {"status": "ready", "score_bp": 3000, "return_bp": 500},
        ],
        k=1,
        bucket_count=3,
    )

    assert result.score_monotonic is True
    assert result.bucket_average_returns_bp == (-300, 100, 500)
    assert result.mae_mfe_ready is False


def test_empty_ready_set_is_fail_closed() -> None:
    result = compute_effectiveness_metrics(
        [{"status": "pending", "score_bp": 9000, "return_bp": 1000}],
        k=5,
    )

    assert result.ready_count == 0
    assert result.precision_at_k_bp is None
    assert result.hit_rate_bp is None
    assert result.payoff_ratio_bp is None
    assert result.score_monotonic is None
