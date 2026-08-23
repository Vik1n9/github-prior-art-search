# -*- coding: utf-8 -*-
"""§11 授權規則驗收：分類、分數、動作、無授權 → high_risk。"""
import pytest

from parse_license import analyze_license, classify_license, license_action, license_fit_score


class TestClassification:
    @pytest.mark.parametrize("spdx,expected", [
        ("MIT", "preferred"),
        ("Apache-2.0", "preferred"),
        ("BSD-3-Clause", "preferred"),
        ("MPL-2.0", "review_required"),
        ("LGPL-3.0", "review_required"),
        ("GPL-3.0", "review_required"),
        ("AGPL-3.0", "high_risk"),
        ("SSPL-1.0", "high_risk"),
        (None, "unknown"),
        ("NOASSERTION", "unknown"),
        ("Other/Custom", "review_required"),  # 清單外 SPDX 保守處理
    ])
    def test_categories(self, config, spdx, expected):
        assert classify_license(spdx, config) == expected


class TestScoresAndActions:
    def test_score_mapping(self, config):
        assert license_fit_score("preferred", config) == 100
        assert license_fit_score("review_required", config) == 40
        assert license_fit_score("high_risk", config) == 10
        assert license_fit_score("unknown", config) == 0

    def test_action_mapping(self, config):
        assert license_action("review_required", config) == "require_manual_review"
        assert license_action("high_risk", config) == "avoid_direct_reuse"
        assert license_action("unknown", config) == "reference_only"


class TestAnalyzeLicense:
    def _metadata(self, spdx=None):
        return {"license": {"spdx_id": spdx} if spdx else None}

    def test_api_field_preferred(self, config):
        info = analyze_license(self._metadata("MIT"), ["src/main.py"], config)
        assert info["spdx_id"] == "MIT"
        assert info["source"] == "api_field"
        assert info["category"] == "preferred"

    def test_no_license_marked_unknown_and_high_risk(self, config):
        info = analyze_license(self._metadata(None), [], config)
        assert info["category"] == "unknown"
        assert info["license_fit_score"] == 0
        assert info["risk_level"] == "high"
        assert info["action"] == "reference_only"

    def test_license_file_but_unparsed_stays_unknown(self, config):
        """存在授權檔但 API 未識別：不得由腳本或模型猜測內容（§15）。"""
        info = analyze_license(self._metadata(None), ["LICENSE"], config)
        assert info["source"] == "license_file_unparsed"
        assert info["category"] == "unknown"

    def test_noassertion_normalized_to_none(self, config):
        info = analyze_license(self._metadata("NOASSERTION"), [], config)
        assert info["spdx_id"] is None
        assert info["category"] == "unknown"
