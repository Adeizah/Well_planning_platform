import pytest
from models.geodesy import (
    common_crs_registry, search_crs_registry, crs_info,
    transformation_report, transform_coordinates, grid_convergence_deg,
)


def test_common_registry_includes_wgs84_and_minna():
    codes = {item["code"] for item in common_crs_registry()}
    assert "EPSG:4326" in codes
    assert "EPSG:4263" in codes
    assert "EPSG:26332" in codes


def test_search_epsg_registry_by_code_and_name():
    assert any(item["code"] == "EPSG:4263" for item in search_crs_registry("4263", 10))
    assert any(item["code"] == "EPSG:26332" for item in search_crs_registry("Minna", 50))
    assert search_crs_registry("", 10) == []


def test_crs_info_reports_minna_datum():
    info = crs_info("EPSG:4263")
    assert "Minna" in info["datum"]


def test_transform_report_has_non_ballpark_wgs84_utm_operation():
    report = transformation_report("EPSG:4326", "EPSG:32632", lon=6.03, lat=5.54)
    assert report["operation_count"] >= 1
    assert report["best_available"] is True


def test_strict_wgs84_to_utm_transform_is_finite_and_roundtrips():
    e, n = transform_coordinates(6.03, 5.54, "EPSG:4326", "EPSG:32632", strict=True, lon=6.03, lat=5.54)
    assert 100000 < e < 900000
    assert 0 < n < 10000000
    lon, lat = transform_coordinates(e, n, "EPSG:32632", "EPSG:4326", strict=True, lon=6.03, lat=5.54)
    assert lon == pytest.approx(6.03, abs=1e-7)
    assert lat == pytest.approx(5.54, abs=1e-7)


def test_grid_convergence_still_works_with_registry_changes():
    assert abs(grid_convergence_deg(5.54, 6.03, "EPSG:32632")) < 1.0
