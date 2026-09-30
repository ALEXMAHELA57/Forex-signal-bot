"""Pick the price feed from config.DATA_SOURCE (imports MT5 only when needed)."""
from . import config


def make_feed():
    if config.DATA_SOURCE == "twelvedata":
        from .api_feed import TwelveDataFeed
        return TwelveDataFeed()
    if config.DATA_SOURCE == "mt5":
        from .mt5_feed import MT5Feed
        return MT5Feed()
    raise ValueError(f"Unknown DATA_SOURCE '{config.DATA_SOURCE}' (use mt5 or twelvedata)")
