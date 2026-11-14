"""Calendar tests use invented observations and cell values."""

from datetime import date, datetime, timezone
from dataclasses import replace
from importlib import import_module
from pathlib import Path

import pytest
from app.models import (
    AnalysisInputs, AnalysisRequest, ApiError, CoverageResult, DailyRecord, ObservationRecord,
    ReleaseRecord, ReleaseSummary, load_settings,
)

CELL = {"type": "Polygon", "coordinates": (((106.0, 10.0), (107.0, 10.0), (107.0, 11.0), (106.0, 11.0), (106.0, 10.0)),)}
CENTER = {"type": "Point", "coordinates": (106.5, 10.5)}


def release():
    summary = ReleaseSummary(release_id="fixture", study_areas=((106, 10, 107, 11),),
        start_date=date(2019, 1, 1), end_date=date(2025, 1, 1), latest_source_dates={"Aqua": date(2024, 3, 1)},
        available_metrics=("observed_hotspot_count", "harmonized_hotspot_count"), allowed_platforms=("Aqua",))
    return ReleaseRecord(summary=summary, method_id="test-method", reference_count_definition="invented",
        code_version="fixture", settings={"minimum_coverage_fraction": 0.8}, source_files=(), source_selection={}, baseline_rules={},
        report_sha256="0" * 64, report_urls=())


def observation(longitude=106.5, latitude=10.5):
    return ObservationRecord(observation_id="o1", source_file_id="f1", source_row_id=1,
        pass_id=None, platform="Aqua", instrument="MODIS", observed_at=datetime(2024, 3, 1, tzinfo=timezone.utc),
        longitude=longitude, latitude=latitude, scan_km=1, track_km=1, frp_mw=0,
        confidence="90", hotspot_type="unknown", quality=(), original_fields={})


def daily(day, value):
    return DailyRecord(release_id="fixture", method_id="test-method", cell_id="cell-1",
        cell_area=CELL, cell_center=CENTER, date=day, source_count=0, reference_count_estimate=value,
        coverage=CoverageResult(expected_days=1, usable_days=1, numerator=1, denominator=1,
                                unit="km2_visits", valid_coverage_fraction=1),
        uncertainty=None, status="observed_zero" if value == 0 else "available")


def test_missing_is_not_zero():
    analysis = import_module("app.analysis")
    query = AnalysisRequest(release_id="fixture", bbox=(106, 10, 107, 11),
        start_date=date(2024, 3, 1), end_date=date(2024, 3, 2),
        metric="harmonized_hotspot_count", aggregation="day")
    inputs = AnalysisInputs(observations=(observation(),), daily=(), opportunities=())
    result = analysis.build_analysis(query, inputs, release())
    assert result.summary.value is None
    assert result.summary.original_count == 1
    assert result.summary.coverage.valid_coverage_fraction is None
    assert result.summary.status == "missing"
    assert result.summary.uncertainty is None
    assert result.summary.baseline is None
    assert "UNCERTAINTY_UNAVAILABLE" in {warning.code for warning in result.summary.warnings}
    unvalidated = analysis.build_analysis(query, inputs, replace(release(), method_id=None))
    assert unvalidated.summary.value is None and unvalidated.summary.status == "not_validated"
    settings = load_settings(Path(__file__).parents[1] / "config/settings.json").api
    analysis.validate_query_domain(query, release(), settings=settings)
    with pytest.raises(ApiError, match="outside this release"):
        analysis.validate_query_domain(query.model_copy(update={"bbox": (105, 10, 107, 11)}), release(), settings=settings)
    with pytest.raises(ApiError, match="not available"):
        analysis.validate_query_domain(query.model_copy(update={"platforms": ("NOAA-20",)}), release(), settings=settings)
    with pytest.raises(ApiError) as conflict:
        analysis.validate_query_domain(query.model_copy(update={"platforms": ("Aqua",)}), release(), settings=settings)
    assert conflict.value.status_code == 409 and conflict.value.code == "REFERENCE_POLICY_CONFLICT"
    with pytest.raises(ApiError, match="dates are outside"):
        analysis.validate_query_domain(query.model_copy(update={"start_date": date(2018, 3, 1)}), release(), settings=settings)
    limited = settings.model_copy(update={"query_limits": {**settings.query_limits, "maximum_days": 1}})
    with pytest.raises(ApiError, match="date range is too large"):
        analysis.validate_query_domain(query.model_copy(update={"end_date": date(2024, 3, 3)}), release(), settings=limited)
    frp_release = replace(release(), summary=release().summary.model_copy(
        update={"available_metrics": ("observed_hotspot_count", "harmonized_hotspot_count", "frp_pass_sum_mw")}))
    with pytest.raises(ApiError) as pass_only:
        analysis.validate_query_domain(query.model_copy(update={"metric": "frp_pass_sum_mw"}), frp_release, settings=settings)
    assert pass_only.value.code == "AGGREGATION_NOT_AVAILABLE"
    edge_points = tuple(replace(observation(longitude, latitude), observation_id=f"edge-{index}")
                        for index, (longitude, latitude) in enumerate(((106, 10), (107, 10), (107, 11), (106, 11)))
                        )
    edges = analysis.build_analysis(query, AnalysisInputs(observations=edge_points, daily=(), opportunities=()), release())
    assert edges.summary.original_count == 4
    unknown_coverage = daily(date(2024, 3, 1), 5).coverage.model_copy(
        update={"numerator": None, "denominator": None, "valid_coverage_fraction": None})
    unknown_daily = DailyRecord(**{**daily(date(2024, 3, 1), 5).__dict__, "coverage": unknown_coverage})
    records = AnalysisInputs(observations=(), daily=(unknown_daily,), opportunities=())
    unknown = analysis.summarize_periods(query, records, release())[0]
    assert unknown.value is None and unknown.status == "missing"
    partial_query = query.model_copy(update={"end_date": date(2024, 3, 3), "aggregation": "month"})
    partial_records = AnalysisInputs(observations=(), daily=(daily(date(2024, 3, 1), 5),), opportunities=())
    partial = analysis.summarize_periods(partial_query, partial_records, release())[0]
    assert partial.value is None and partial.partial_value == 5 and partial.status == "partial"


def test_equal_historical_window():
    analysis = import_module("app.analysis")
    query = AnalysisRequest(release_id="fixture", bbox=(106, 10, 107, 11),
        start_date=date(2024, 2, 28), end_date=date(2024, 3, 2),
        metric="harmonized_hotspot_count", aggregation="month",
        comparison={"mode": "same_elapsed_days", "baseline_start_year": 2019, "baseline_end_year": 2023})
    values = [daily(date(year, 2, 28), total) for year, total in zip(range(2019, 2024), (0, 2, 4, 6, 8))]
    values += [daily(date(year, 3, 1), 0) for year in range(2019, 2024)]
    values += [daily(date(2020, 2, 29), 999), daily(date(2024, 2, 28), 3),
               daily(date(2024, 2, 29), 999), daily(date(2024, 3, 1), 3)]
    result = analysis.compare_history(query, AnalysisInputs(observations=(), daily=tuple(values), opportunities=()), release())
    assert result.status == "available" and result.median == 4
    assert result.absolute_difference == 2 and result.percentage_difference == 50
    assert result.years_used == (2019, 2020, 2021, 2022, 2023)
    analysis_inputs = AnalysisInputs(observations=(observation(),), daily=tuple(values), opportunities=())
    built = analysis.build_analysis(query, analysis_inputs, release())
    assert built.summary.value == 1005 and built.summary.baseline.median == 4
    assert [period.value for period in built.calendar] == [1002, 3]
    monthly = analysis.summarize_periods(query, AnalysisInputs(observations=(observation(),), daily=tuple(values), opportunities=()), release())
    assert [period.start_date for period in monthly] == [date(2024, 2, 28), date(2024, 3, 1)]
    assert monthly[0].baseline.median == 4 and monthly[1].baseline.median == 0
    assert all(period.partial_calendar_period for period in monthly)
    assert [period.original_count for period in monthly] == [0, 1]
    zero_values = tuple(daily(row.date, 0) for row in values)
    zero = analysis.compare_history(query, AnalysisInputs(observations=(), daily=zero_values, opportunities=()), release())
    assert zero.status == "available" and zero.median == 0 and zero.percentage_difference is None
    assert "ZERO_BASELINE" in {warning.code for warning in zero.warnings}
    short_comparison = query.comparison.model_copy(update={"baseline_start_year": 2020})
    short_query = query.model_copy(update={"comparison": short_comparison})
    short = analysis.compare_history(short_query, AnalysisInputs(observations=(), daily=tuple(values), opportunities=()), release())
    assert short.status == "insufficient_baseline" and len(short.years_used) == 4
    missing_year = tuple(row for row in values if row.date != date(2019, 3, 1))
    excluded = analysis.compare_history(query, AnalysisInputs(observations=(), daily=missing_year, opportunities=()), release())
    assert excluded.status == "insufficient_baseline" and excluded.excluded_years[2019] == "partial"
    settings = load_settings(Path(__file__).parents[1] / "config/settings.json").api
    old_comparison = query.comparison.model_copy(update={"baseline_start_year": 2018})
    with pytest.raises(ApiError, match="baseline is outside"):
        analysis.validate_query_domain(query.model_copy(update={"comparison": old_comparison}), release(), settings=settings)
    daily_query = query.model_copy(update={"aggregation": "day"})
    periods = analysis.summarize_periods(daily_query, AnalysisInputs(observations=(), daily=tuple(values), opportunities=()), release())
    assert [period.start_date for period in periods] == [date(2024, 2, 28), date(2024, 2, 29), date(2024, 3, 1)]


def test_tiny_selection_has_no_spatial_support():
    analysis = import_module("app.analysis")
    query = AnalysisRequest(release_id="fixture", bbox=(106, 10, 106.1, 10.1),
        start_date=date(2024, 3, 1), end_date=date(2024, 3, 2),
        metric="harmonized_hotspot_count", aggregation="day")
    inputs = AnalysisInputs(observations=(observation(106.05, 10.05),), daily=(daily(date(2024, 3, 1), 5),), opportunities=())
    result = analysis.build_analysis(query, inputs, release())
    assert result.used_area is None and result.summary.value is None
    assert result.summary.original_count == 1
    assert "INSUFFICIENT_SPATIAL_SUPPORT" in {warning.code for warning in result.summary.warnings}
    edge_query = query.model_copy(update={"bbox": (106.5, 10.5, 107, 11)})
    cell_inputs = AnalysisInputs(observations=(), daily=(daily(date(2024, 3, 1), 5),), opportunities=())
    selected = analysis.build_analysis(edge_query, cell_inputs, release())
    assert selected.used_area["type"] == "Polygon"
    ring = selected.used_area["coordinates"][0]
    assert min(point[0] for point in ring) == 106.0 and max(point[1] for point in ring) == 11.0
    assert cell_inputs.daily[0].cell_center == CENTER
    invalid_cell = replace(daily(date(2024, 3, 1), 5), cell_area={
        "type": "Polygon", "coordinates": (((106, 10), (107, 11), (106, 11), (107, 10), (106, 10)),)})
    with pytest.raises(ApiError, match="invalid geometry"):
        analysis.build_analysis(edge_query, AnalysisInputs(observations=(), daily=(invalid_cell,), opportunities=()), release())
