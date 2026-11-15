"""Calculate results from one fixed release."""

from datetime import date, datetime, timedelta, timezone
from statistics import median

from app.models import (
    AnalysisInputs, AnalysisRequest, AnalysisResponse, ApiError, ApiSettings,
    CoverageResult, DailyRecord, HistoricalComparison, Notice, PeriodResult,
    ReleaseRecord, HotspotQuery, ExportRequest,
)


def validate_query_domain(
    query: AnalysisRequest | HotspotQuery | ExportRequest,
    release: ReleaseRecord, *, settings: ApiSettings,
) -> None:
    """Reject requests outside this release and its stored limits."""
    summary = release.summary
    if query.release_id != summary.release_id:
        raise ApiError(404, "RELEASE_NOT_FOUND", "The requested release does not exist.")
    if not any(_contains(area, query.bbox) for area in summary.study_areas):
        raise ApiError(422, "OUTSIDE_RELEASE_DOMAIN", "The area is outside this release.")
    if query.start_date < summary.start_date or query.end_date > summary.end_date:
        raise ApiError(422, "OUTSIDE_RELEASE_DOMAIN", "The dates are outside this release.")
    if (query.end_date - query.start_date).days > settings.query_limits["maximum_days"]:
        raise ApiError(422, "QUERY_LIMIT_EXCEEDED", "The date range is too large.")
    platforms = query.platforms
    if platforms is not None and not set(platforms).issubset(summary.allowed_platforms):
        raise ApiError(422, "PLATFORM_NOT_AVAILABLE", "A platform is not available in this release.")
    metric = getattr(query, "metric", None)
    aggregation = getattr(query, "aggregation", None)
    if metric is not None:
        if metric not in summary.available_metrics:
            raise ApiError(409, "METRIC_NOT_AVAILABLE", "This metric is not available.")
        if metric == "frp_pass_sum_mw" and aggregation is not None:
            raise ApiError(422, "AGGREGATION_NOT_AVAILABLE", "FRP is available by pass only.")
        if metric == "observed_hotspot_count" and not platforms:
            raise ApiError(422, "PLATFORM_REQUIRED", "Choose at least one source platform.")
        if metric == "harmonized_hotspot_count" and platforms is not None:
            raise ApiError(409, "REFERENCE_POLICY_CONFLICT", "This release fixes its source policy.")
    comparison = getattr(query, "comparison", None)
    if comparison is not None:
        years = comparison.baseline_end_year - comparison.baseline_start_year + 1
        if years > settings.query_limits["maximum_baseline_years"]:
            raise ApiError(422, "QUERY_LIMIT_EXCEEDED", "The baseline range is too large.")
        baseline_start = _map_year(query.start_date, comparison.baseline_start_year)
        baseline_end = _map_year(query.end_date, comparison.baseline_end_year)
        if baseline_start is None or baseline_end is None or baseline_start < summary.start_date:
            raise ApiError(422, "OUTSIDE_RELEASE_DOMAIN", "The baseline is outside this release.")
        if comparison.baseline_end_year >= query.start_date.year:
            raise ApiError(422, "INVALID_BASELINE", "Baseline years must precede the query year.")


def summarize_periods(
    query: AnalysisRequest, records: AnalysisInputs, release: ReleaseRecord,
) -> tuple[PeriodResult, ...]:
    """Return every requested day or month, including periods with no data."""
    periods = _calendar_periods(query.start_date, query.end_date, query.aggregation)
    return tuple(_summarize(query, records, release, start, end) for start, end in periods)


def compare_history(
    query: AnalysisRequest, records: AnalysisInputs, release: ReleaseRecord,
) -> HistoricalComparison | None:
    """Compare the same calendar dates in earlier years."""
    comparison = query.comparison
    if comparison is None:
        return None
    selected = _selected_cells(query, records.daily)
    if not selected:
        return _insufficient({}, "INSUFFICIENT_SPATIAL_SUPPORT")
    wanted = _query_days(query.start_date, query.end_date)
    wanted = tuple(day for day in wanted if not (day.month == 2 and day.day == 29))
    if not wanted:
        return _insufficient({}, "NO_COMPARABLE_DATES")
    values: list[float] = []
    used: list[int] = []
    excluded: dict[int, str] = {}
    for year in range(comparison.baseline_start_year, comparison.baseline_end_year + 1):
        mapped = tuple(_map_year(day, year) for day in wanted)
        if any(day is None for day in mapped):
            excluded[year] = "INVALID_CALENDAR_DATE"
            continue
        daily = _daily_for(selected, (day for day in mapped if day is not None), records.daily)
        result = _estimate(daily, len(mapped), len(selected), release, query.metric)
        if result["value"] is None or result["status"] not in {"available", "observed_zero"}:
            excluded[year] = result["status"]
            continue
        values.append(float(result["value"]))
        used.append(year)
    if len(used) < 5:
        return _insufficient(excluded, "FEWER_THAN_FIVE_USABLE_YEARS", tuple(used))
    historical_median = float(median(values))
    target_rows = _daily_for(selected, wanted, records.daily)
    target = _estimate(target_rows, len(wanted), len(selected), release, query.metric)
    if target["value"] is None:
        return _insufficient(excluded, "TARGET_VALUE_UNAVAILABLE", tuple(used))
    difference = float(target["value"]) - historical_median
    warnings: list[Notice] = []
    percentage = None
    if historical_median == 0:
        warnings.append(Notice(code="ZERO_BASELINE", message="Percentage difference is not defined."))
    else:
        percentage = difference / historical_median * 100
    return HistoricalComparison(
        status="available", median=historical_median, years_used=tuple(used),
        excluded_years=excluded, absolute_difference=difference,
        percentage_difference=percentage, warnings=tuple(warnings),
    )


def build_analysis(
    query: AnalysisRequest, records: AnalysisInputs, release: ReleaseRecord,
) -> AnalysisResponse:
    """Build one summary and all calendar periods without changing inputs."""
    if query.metric == "frp_pass_sum_mw":
        raise ApiError(422, "AGGREGATION_NOT_AVAILABLE", "FRP is available by pass only.")
    selected = _selected_cells(query, records.daily)
    used_area = _union_cells(selected)
    summary = _summarize(query, records, release, query.start_date, query.end_date)
    calendar = summarize_periods(query, records, release)
    return AnalysisResponse(
        query=query, requested_bbox=query.bbox, used_area=used_area,
        release_id=release.summary.release_id, method_id=release.method_id,
        reference_count_definition=release.reference_count_definition,
        unit=_unit(query.metric), latest_source_date=_latest_date(release, query.platforms),
        response_time_ms=0.0, summary=summary, calendar=calendar,
        warnings=summary.warnings,
    )


def _summarize(query, records, release, start, end, *, compare=True):
    days = _query_days(start, end)
    selected = _selected_cells(query, records.daily)
    daily = _daily_for(selected, days, records.daily)
    estimated = _estimate(daily, len(days), len(selected), release, query.metric)
    points = _selected_points(query, records, start, end)
    value = estimated["value"]
    status = estimated["status"]
    if query.metric == "observed_hotspot_count":
        value = len(points)
        status = "available" if points else "observed_zero"
        partial_value = None
    else:
        partial_value = estimated["partial_value"]
    warnings = list(estimated["warnings"])
    if not selected and records.daily:
        warnings.append(Notice(code="INSUFFICIENT_SPATIAL_SUPPORT", message="No grid cell center is inside the selected area."))
    if query.metric == "harmonized_hotspot_count" and release.method_id is None:
        value, status = None, "not_validated"
        partial_value = None
    if query.metric == "harmonized_hotspot_count" and status == "available" and estimated["low_coverage"]:
        value, status = None, "low_coverage"
    baseline_query = query.model_copy(update={"start_date": start, "end_date": end})
    baseline = compare_history(baseline_query, records, release) if compare and query.comparison else None
    latest = _latest_date(release, query.platforms)
    old_data = latest is not None and (datetime.now(timezone.utc).date() - latest).days > 3
    partial = query.aggregation == "month" and (start.day != 1 or end.day != 1)
    return PeriodResult(
        start_date=start, end_date=end, value=value,
        partial_value=partial_value, original_count=len(points),
        original_count_rule="Source points inside the closed rectangle and half-open UTC dates.",
        coverage=estimated["coverage"], baseline=baseline,
        uncertainty=None, status=status, partial_calendar_period=partial,
        old_data=old_data,
        warnings=tuple((*warnings, Notice(code="UNCERTAINTY_UNAVAILABLE", message="No checked uncertainty method is available."))),
    )


def _estimate(daily: tuple[DailyRecord, ...], expected_days: int, cell_count: int, release: ReleaseRecord, metric: str):
    if not daily:
        return {"value": None, "partial_value": None, "status": "missing", "low_coverage": False,
                "coverage": _coverage(expected_days, None, None, None, None),
                "warnings": [Notice(code="COVERAGE_UNKNOWN", message="Coverage is not available.")]}
    expected_rows = expected_days * cell_count
    missing = len(daily) < expected_rows
    values = [item.reference_count_estimate for item in daily]
    if metric == "observed_hotspot_count":
        values = [float(item.source_count) for item in daily]
    elif metric == "active_cell_count":
        by_day: dict[date, int] = {}
        for item in daily:
            by_day[item.date] = by_day.get(item.date, 0) + int(item.source_count > 0)
        values = list(by_day.values())
    elif metric == "valid_coverage_fraction":
        values = [item.coverage.valid_coverage_fraction for item in daily]
    available = [float(value) for value in values if value is not None]
    partial_value = None
    threshold = release.settings.get("minimum_coverage_fraction")
    coverage, fraction = _coverage_summary(daily, expected_days, expected_rows, threshold)
    known_coverage = coverage.valid_coverage_fraction is not None
    if missing:
        status, value = ("partial" if available else "missing"), None
    elif any(value is None for value in values):
        status, value = ("partial" if available else "missing"), None
    elif not known_coverage or fraction is None:
        status, value = "missing", None
    elif metric == "valid_coverage_fraction":
        status, value = "available", fraction
    elif threshold is None:
        status, value = "not_validated", None
    elif fraction is not None and fraction < threshold:
        status, value = "low_coverage", None
    else:
        value = sum(available)
        status = "observed_zero" if value == 0 else "available"
    if status == "partial":
        partial_value = sum(available) if available else None
    warnings = []
    if fraction is None:
        warnings.append(Notice(code="COVERAGE_UNKNOWN", message="Coverage is not available for every requested day."))
    if status == "low_coverage":
        warnings.append(Notice(code="LOW_COVERAGE", message="Coverage is below the release threshold."))
    return {"value": value, "partial_value": partial_value, "status": status,
            "low_coverage": status == "low_coverage", "coverage": coverage, "warnings": warnings}


def _selected_cells(query, rows):
    west, south, east, north = query.bbox
    unique = {}
    for row in rows:
        x, y = row.cell_center["coordinates"]
        if west <= x <= east and south <= y <= north:
            previous = unique.setdefault(row.cell_id, row)
            if previous.cell_area != row.cell_area or previous.cell_center != row.cell_center:
                raise ApiError(500, "INVALID_RELEASE", "A grid cell has conflicting geometry.")
    return tuple(unique[key] for key in sorted(unique))


def _selected_points(query, records, start=None, end=None):
    platforms = set(query.platforms or ())
    start = start or query.start_date
    end = end or query.end_date
    return tuple(row for row in records.observations if (
        start <= row.observed_at.date() < end
        and query.bbox[0] <= row.longitude <= query.bbox[2]
        and query.bbox[1] <= row.latitude <= query.bbox[3]
        and (not platforms or row.platform in platforms)
    ))


def _daily_for(cells, days, rows):
    ids = {row.cell_id for row in cells}
    wanted = set(days)
    return tuple(row for row in rows if row.cell_id in ids and row.date in wanted)


def _union_cells(cells):
    if not cells:
        return None
    from shapely.geometry import mapping, shape
    from shapely import union_all

    areas = [shape(row.cell_area) for row in cells]
    if any(area.is_empty or not area.is_valid for area in areas):
        raise ApiError(500, "INVALID_RELEASE", "A grid cell has invalid geometry.")
    union = union_all(areas)
    if union.is_empty or not union.is_valid:
        raise ApiError(500, "INVALID_RELEASE", "The selected grid area is invalid.")
    geometry = mapping(union)
    return {"type": geometry["type"], "coordinates": geometry["coordinates"]}


def _calendar_periods(start, end, aggregation):
    if aggregation == "day":
        return tuple((day, day + timedelta(days=1)) for day in _query_days(start, end))
    result = []
    cursor = start
    while cursor < end:
        month_start = cursor.replace(day=1)
        next_month = _period_end(cursor, "month")
        result.append((cursor, min(end, next_month)))
        cursor = next_month
    return tuple(result)


def _query_days(start, end):
    return tuple(start + timedelta(days=index) for index in range((end - start).days))


def _period_end(day, aggregation):
    if aggregation == "day":
        return day + timedelta(days=1)
    year, month = day.year, day.month
    return date(year + (month == 12), 1 if month == 12 else month + 1, 1)


def _map_year(day, year):
    try:
        return day.replace(year=year)
    except ValueError:
        return None


def _contains(outer, inner):
    return outer[0] <= inner[0] and outer[1] <= inner[1] and outer[2] >= inner[2] and outer[3] >= inner[3]


def _coverage(expected, usable, numerator, denominator, fraction):
    return CoverageResult(expected_days=expected, usable_days=usable, numerator=numerator,
                          denominator=denominator, unit="km2_visits", valid_coverage_fraction=fraction)


def _coverage_summary(daily, expected_days, expected_rows, threshold):
    dates = {item.date for item in daily}
    fractions = [item.coverage.valid_coverage_fraction for item in daily]
    complete = len(daily) == expected_rows and all(value is not None for value in fractions)
    complete = complete and all(item.coverage.numerator is not None and item.coverage.denominator is not None for item in daily)
    numerator = sum(item.coverage.numerator for item in daily) if complete else None
    denominator = sum(item.coverage.denominator for item in daily) if complete else None
    fraction = numerator / denominator if numerator is not None and denominator else None
    usable = None
    if complete and len(dates) == expected_days and threshold is not None:
        usable = sum((_coverage_fraction([item for item in daily if item.date == day]) or 0) >= threshold for day in dates)
    return _coverage(expected_days, usable, numerator, denominator, fraction), fraction


def _coverage_fraction(rows):
    if any(row.coverage.numerator is None or row.coverage.denominator is None for row in rows):
        return None
    numerator = sum(row.coverage.numerator for row in rows)
    denominator = sum(row.coverage.denominator for row in rows)
    return numerator / denominator if denominator > 0 else None


def _insufficient(excluded, code, years=()):
    return HistoricalComparison(
        status="insufficient_baseline", median=None, years_used=years,
        excluded_years=excluded,
        absolute_difference=None, percentage_difference=None,
        warnings=(Notice(code=code, message="Five usable baseline years are required."),),
    )


def _latest_date(release, platforms):
    dates = [day for platform, day in release.summary.latest_source_dates.items()
             if platforms is None or platform in platforms]
    return max(dates) if dates else None


def _unit(metric):
    return {"observed_hotspot_count": "detections", "harmonized_hotspot_count": "estimated detections",
            "active_cell_count": "cells", "frp_pass_sum_mw": "MW", "valid_coverage_fraction": "fraction"}[metric]
