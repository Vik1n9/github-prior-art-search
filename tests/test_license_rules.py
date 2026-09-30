import pytest

from scripts.parse_license import analyze_license, classify_license


class TestClassification:
    @pytest.mark.parametrize("spdx,expected", [
        ("MIT", "preferred"),
        ("Apache-2.0", "preferred"),
        ("ISC", "preferred"),
        ("Unlicense", "preferred"),
        ("0BSD", "preferred"),
        ("MPL-2.0", "review_required"),
        ("LGPL-2.1", "review_required"),
        ("GPL-3.0", "review_required"),
        ("AGPL-3.0", "high_risk"),
        ("BUSL-1.1", "high_risk"),
        ("Elastic-2.0", "high_risk"),
        (None, "unknown"),
        ("NOASSERTION", "unknown"),
        ("Other/Custom", "review_required"),
    ])
    def test_categories(self, config, spdx, expected):
        assert classify_license(spdx, config) == expected


class TestAnalyzeLicense:
    def _metadata(self, spdx=None):
        return {"license": {"spdx_id": spdx} if spdx else None}

    def test_api_field(self, config):
        info = analyze_license(self._metadata("MIT"), ["src/main.py"], config)
        assert info == {"spdx_id": "MIT", "source": "api_field",
                        "category": "preferred", "risk_level": "low"}

    def test_no_license_is_unknown_and_high_risk(self, config):
        info = analyze_license(self._metadata(None), [], config)
        assert info["category"] == "unknown"
        assert info["source"] == "none"
        assert info["risk_level"] == "high"

    def test_license_file_but_unparsed_stays_unknown(self, config):
        info = analyze_license(self._metadata(None), ["LICENSE"], config)
        assert info["source"] == "license_file_unparsed"
        assert info["category"] == "unknown"

    def test_noassertion_normalized_to_none(self, config):
        info = analyze_license(self._metadata("NOASSERTION"), [], config)
        assert info["spdx_id"] is None
