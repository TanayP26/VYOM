import pytest

from app.features import FeatureConfig, TemporalFeatureBuilder
from app.streaming_benchmark import (
    LEGACY_COMPARATOR_FEATURE_CONFIG,
    _assert_legacy_builder_contract,
    _legacy_feature_config,
)

HISTORY = {"approved_cap_rows": 10000}

def test_m13_legacy_config_is_explicit_scale1():
    cfg = _legacy_feature_config(HISTORY)
    assert tuple(cfg.scales) == (1,)
    assert cfg.max_history_rows == 10000
    assert tuple(LEGACY_COMPARATOR_FEATURE_CONFIG.scales) == (1,)

def test_runtime_contract_accepts_exact_scale1_builder():
    builder = TemporalFeatureBuilder(90.0, _legacy_feature_config(HISTORY))
    assert tuple(_assert_legacy_builder_contract(builder, HISTORY).scales) == (1,)

def test_runtime_contract_rejects_default_scale14_builder():
    builder = TemporalFeatureBuilder(90.0, FeatureConfig(max_history_rows=10000))
    with pytest.raises(RuntimeError, match="legacy feature-builder contract drift"):
        _assert_legacy_builder_contract(builder, HISTORY)

def test_scale1_longest_window_is_2700_seconds_at_90s_initial_cadence():
    builder = TemporalFeatureBuilder(90.0, _legacy_feature_config(HISTORY))
    assert builder.metadata()["windows_seconds"] == {"1": 2700.0}
