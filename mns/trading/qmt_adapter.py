class QMTTradingAdapter:
    def place_order(self, *args, **kwargs):
        raise RuntimeError("Live QMT trading is disabled in phase 1.")
