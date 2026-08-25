import pandas as pd

from stato_italia.delivery import _derived


def test_profile_delivery_keeps_every_metric_analytics_summary() -> None:
    rows = pd.DataFrame([
        {"analytics_id": "a", "algorithm_version": "soil-analytics-v1", "metric_id": "soil_net_consumption_hectares"},
        {"analytics_id": "b", "algorithm_version": "soil-analytics-v1", "metric_id": "soil_consumed_share"},
    ])
    summaries = _derived(rows)
    assert [item["metricId"] for item in summaries] == ["soil_net_consumption_hectares", "soil_consumed_share"]
