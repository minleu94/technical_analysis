from scripts.check_ml_shadow_boundary import main


def test_shadow_boundary_cli_passes_repository() -> None:
    assert main([]) == 0
