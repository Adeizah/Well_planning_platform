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


def test_projected_grid_coordinates_are_normalized_to_metres_for_foot_crs():
    from models.geodesy import projected_coordinates_to_metres, metres_to_projected_coordinates
    # EPSG:2263 uses US survey feet; round-trip should preserve the coordinate.
    e_m, n_m = projected_coordinates_to_metres(1000000.0, 200000.0, "EPSG:2263")
    assert e_m == pytest.approx(304800.609601, rel=1e-8)
    assert n_m == pytest.approx(60960.1219202, rel=1e-8)
    e_native, n_native = metres_to_projected_coordinates(e_m, n_m, "EPSG:2263")
    assert e_native == pytest.approx(1000000.0)
    assert n_native == pytest.approx(200000.0)


def test_geographic_crs_rejected_for_projected_grid_units():
    from models.geodesy import projected_unit_to_metre_factor
    with pytest.raises(ValueError):
        projected_unit_to_metre_factor("EPSG:4326")


def test_projected_grid_reprojection_preserves_physical_location_between_utm_zones():
    from models.geodesy import transform_projected_grid_metres, transform_coordinates
    # Start from a WGS84 location, project to UTM 32N, then reproject to UTM 31N.
    e32, n32 = transform_coordinates(6.03, 5.54, "EPSG:4326", "EPSG:32632", strict=True, lon=6.03, lat=5.54)
    e31, n31 = transform_projected_grid_metres(e32, n32, "EPSG:32632", "EPSG:32631")
    lon, lat = transform_coordinates(e31, n31, "EPSG:32631", "EPSG:4326", strict=True)
    assert lon == pytest.approx(6.03, abs=1e-7)
    assert lat == pytest.approx(5.54, abs=1e-7)


def test_missing_datum_operation_is_not_silently_used_for_reprojection():
    from models.geodesy import transform_projected_grid_metres
    # This environment does not include a suitable high-accuracy Minna/WGS84 grid operation.
    with pytest.raises(ValueError):
        transform_projected_grid_metres(500000.0, 600000.0, "EPSG:32632", "EPSG:26332")


def test_transformation_report_does_not_crash_for_minna_projected_crs():
    # A diagnostic report should survive PROJ rejecting an AOI-specific operation.
    report = transformation_report("EPSG:26393", "EPSG:4326", lon=5.75, lat=19.26)
    assert report["source_crs"]
    assert report["target_crs"]
    assert "best_available" in report
    assert "description" in report


def test_minna_projected_crs_is_recognized_even_if_transform_accuracy_is_unknown():
    info = crs_info("EPSG:26393")
    assert info["type"] == "Projected"
    assert "Minna" in info["datum"]
