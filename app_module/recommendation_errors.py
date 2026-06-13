class RecommendationUniverseTooSmallError(ValueError):
    """橫斷面推薦百分位排名時，合格個股母體數量低於設定最低限制之例外。"""
    def __init__(self, actual_size: int, minimum_size: int) -> None:
        self.actual_size = actual_size
        self.minimum_size = minimum_size
        super().__init__(
            f"eligible universe too small: actual={actual_size}, minimum={minimum_size}"
        )
