from __future__ import annotations

import pandas as pd

from mns.market.sector_provider.akshare_sector_provider import AKShareSectorProvider
from mns.market.sector_provider.base import SectorProvider
from mns.market.sector_provider.sector_normalizer import SectorNormalizer
from mns.market.sector_provider.service import SectorSyncConfig, SectorSyncService
from mns.market.sector_provider.sector_store import SectorStore


class _FakeAKModule:
    @staticmethod
    def stock_board_industry_name_em():
        return pd.DataFrame(
            [
                {"板块名称": "半导体", "板块代码": "BK1234", "最新价": 100.0, "涨跌幅": 2.5, "上涨家数": 8, "下跌家数": 2, "领涨股": "北方华创", "领涨股-涨跌幅": 7.8},
            ]
        )

    @staticmethod
    def stock_board_concept_name_em():
        return pd.DataFrame(
            [
                {"板块名称": "人工智能", "板块代码": "BK5678", "最新价": 101.0, "涨跌幅": 3.5, "上涨家数": 9, "下跌家数": 1, "领涨股": "科大讯飞", "领涨股-涨跌幅": 8.8},
            ]
        )

    @staticmethod
    def stock_board_industry_cons_em(symbol: str):
        assert symbol == "半导体"
        return pd.DataFrame([{"代码": "688981", "名称": "中芯国际"}])

    @staticmethod
    def stock_board_concept_cons_em(symbol: str):
        assert symbol == "人工智能"
        return pd.DataFrame([{"代码": "002230", "名称": "科大讯飞"}])


class _FakeSectorProvider(SectorProvider):
    name = "fake"

    def get_sector_list(self, sector_types: list[str] | None = None) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"sector_name": "半导体", "source_sector_code": "BK1234", "sector_type": "industry"},
                {"sector_name": "人工智能", "source_sector_code": "BK5678", "sector_type": "concept"},
            ]
        )

    def get_sector_stocks(
        self,
        *,
        sector_name: str,
        sector_type: str | None = None,
        source_sector_code: str | None = None,
    ) -> pd.DataFrame:
        if sector_name == "半导体":
            return pd.DataFrame([{"代码": "688981", "名称": "中芯国际"}])
        return pd.DataFrame([{"代码": "002230", "名称": "科大讯飞"}])

    def get_sector_daily(self, trade_date: str | None = None, sector_types: list[str] | None = None) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "板块名称": "半导体",
                    "板块代码": "BK1234",
                    "涨跌幅": 2.5,
                    "总成交额": 10_000_000.0,
                    "上涨家数": 8,
                    "下跌家数": 2,
                    "领涨股": "中芯国际",
                    "领涨股-涨跌幅": 7.8,
                },
                {
                    "板块名称": "人工智能",
                    "板块代码": "BK5678",
                    "涨跌幅": 3.5,
                    "总成交额": 12_000_000.0,
                    "上涨家数": 9,
                    "下跌家数": 1,
                    "领涨股": "科大讯飞",
                    "领涨股-涨跌幅": 8.8,
                },
            ]
        )


def test_sector_normalizer_normalizes_stock_codes():
    normalizer = SectorNormalizer("akshare")
    assert normalizer.normalize_stock_code("688981") == "688981.SH"
    assert normalizer.normalize_stock_code("sz.002230") == "002230.SZ"
    assert normalizer.normalize_stock_code("002230.SZ") == "002230.SZ"


def test_akshare_sector_provider_with_fake_module():
    provider = AKShareSectorProvider(ak_module=_FakeAKModule())

    sectors = provider.get_sector_list()
    stocks = provider.get_sector_stocks(sector_name="半导体", sector_type="industry")
    daily = provider.get_sector_daily()

    assert set(sectors["sector_type"]) == {"industry", "concept"}
    assert sectors["sector_name"].tolist() == ["半导体", "人工智能"]
    assert stocks.iloc[0]["代码"] == "688981"
    assert not daily.empty


def test_sector_sync_service_persists_snapshot(tmp_path):
    db_path = tmp_path / "sector.duckdb"
    result = SectorSyncService(
        provider=_FakeSectorProvider(),
        config=SectorSyncConfig(db_path=str(db_path)),
    ).run()

    store = SectorStore(db_path)
    sectors = store.list_sectors(source="fake")
    stocks = store.get_stock_sectors("688981.SH")

    assert result["sector_count"] == 2
    assert result["mapping_count"] == 2
    assert result["sector_daily_count"] == 2
    assert result["sector_strength_count"] == 2
    assert result["sector_leader_count"] == 2
    assert sectors["sector_name"].tolist() == ["人工智能", "半导体"]
    assert stocks.iloc[0]["sector_name"] == "半导体"


def test_qmt_sector_provider_supports_raw_snapshot(tmp_path):
    snapshot = tmp_path / "sector_snapshot.json"
    snapshot.write_text(
        """
        {
          "sectors": [
            {
              "sector_name": "半导体",
              "source_sector_code": "semi",
              "sector_type": "industry",
              "stocks": [
                {"stock_code": "688981", "stock_name": "中芯国际"},
                {"stock_code": "603986.SH", "stock_name": "兆易创新"}
              ]
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    from mns.market.sector_provider.qmt_sector_provider import QMTSectorProvider

    provider = QMTSectorProvider(raw_snapshot_path=snapshot)
    sectors = provider.get_sector_list(["industry"])
    members = provider.get_sector_stocks(sector_name="半导体", sector_type="industry", source_sector_code="semi")

    assert sectors.iloc[0]["sector_name"] == "半导体"
    assert members["stock_code"].tolist() == ["688981", "603986.SH"]


def test_qmt_sector_snapshot_supports_flat_board_snapshot_csv(tmp_path):
    snapshot = tmp_path / "ths_board_snapshot.csv"
    pd.DataFrame(
        [
            {"board_name": "semi", "board_code": "881121", "stock_code": "688981.SH", "stock_name": "smic"},
            {"board_name": "semi", "board_code": "881121", "stock_code": "603986.SH", "stock_name": "giga"},
        ]
    ).to_csv(snapshot, index=False)

    from mns.market.sector_provider.qmt_sector_snapshot import load_qmt_sector_snapshot

    sectors, members = load_qmt_sector_snapshot(snapshot)

    assert sectors.iloc[0]["sector_name"] == "semi"
    assert str(sectors.iloc[0]["source_sector_code"]) == "881121"
    assert sectors.iloc[0]["sector_type"] == "industry"
    assert members["stock_code"].tolist() == ["688981.SH", "603986.SH"]
