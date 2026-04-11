"""Tests for app/config.py — verify all required constants exist and are sane."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.config as cfg


def test_max_top_k_exists():
    assert hasattr(cfg, 'MAX_TOP_K'), "MAX_TOP_K must be defined in config.py"


def test_max_top_k_value():
    assert cfg.MAX_TOP_K == 15


def test_top_k_less_than_max():
    assert cfg.TOP_K < cfg.MAX_TOP_K, "Default TOP_K should be less than MAX_TOP_K"


def test_top_k_positive():
    assert cfg.TOP_K >= 1


def test_confidence_threshold_range():
    assert 0 < cfg.CONFIDENCE_THRESHOLD < 1


def test_embedding_dim():
    assert cfg.EMBEDDING_DIM == 384


def test_paths_are_relative():
    for attr in ('DB_PATH', 'FAISS_PATH', 'ID_MAP_PATH', 'DOCUMENTS_DIR'):
        val = getattr(cfg, attr)
        assert not Path(val).is_absolute(), f"{attr} must be a relative path, got {val!r}"
