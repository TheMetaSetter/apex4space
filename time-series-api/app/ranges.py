"""One inclusive date-range contract for maps, statistics and educational chat."""
from datetime import date, timedelta
import math
from fastapi import Request
from pydantic import Field, model_validator
from app.area_queries import _Query, _area
from app.models import ApiError


class DateRange(_Query):
    start_date: date
    end_date: date
    offset: int = Field(default=0, ge=0)
    page_size: int = Field(default=1000, ge=1, le=10000)
    include_geometry: bool = True
    bbox: tuple[float, float, float, float] | None = None

    @model_validator(mode='after')
    def check_bounds(self):
        if self.start_date > self.end_date or self.end_date == date.max:
            raise ValueError('The start date must not be after the end date.')
        if self.bbox:
            west, south, east, north = self.bbox
            if not (-180 <= west <= 180 and -180 <= east <= 180 and -86 <= south <= north <= 86):
                raise ValueError('Use a valid longitude/latitude viewport. West > east crosses the date line.')
        return self


def statistics(start, end, rows, counts):
    """end is excluded internally; divide by selected days, not observation coverage."""
    days, monthly, day = [], {}, start
    while day < end:
        count = counts.get(str(day), 0)
        days.append({'date': str(day), 'active_cell_count': count, 'status': 'coverage_unknown'})
        month = str(day)[:7]
        monthly[month] = monthly.get(month, 0) + count
        day += timedelta(days=1)
    peak = max(counts, key=lambda key: (counts[key], key)) if counts else None
    total = sum(counts.values())
    return {'start_date': str(start), 'end_date': str(end - timedelta(days=1)), 'end_inclusive': True,
        'selected_days': (end-start).days, 'unique_active_cells': len(rows), 'total_cell_days': total,
        'average_daily_active_cells': total / (end-start).days, 'peak_date': peak,
        'peak_count': counts.get(peak, 0), 'days': days, 'monthly_counts': monthly}


def view_filter(bbox):
    if bbox is None:
        return lambda grid: True
    west,south,east,north=bbox
    radius=6378137.0
    left,right=math.radians(west)*radius/10000,math.radians(east)*radius/10000
    bottom=radius*math.log(math.tan(math.pi/4+math.radians(south)/2))/10000
    top=radius*math.log(math.tan(math.pi/4+math.radians(north)/2))/10000
    def matches(grid):
        row_text,column_text=grid.removeprefix('E3857_10K_R').split('_C')
        row,column=int(row_text),int(column_text)
        longitude=column<=right and column+1>=left if west<=east else column+1>=left or column<=right
        return longitude and row+1>=bottom and row<=top
    return matches


def intersects_view(grid,bbox):
    return view_filter(bbox)(grid)


def range_result(query, request):
    from app.parquet_data import manifest_for, _range_counts, provenance, _check_date_range
    if request.app.state.settings.storage.data_format != 'parquet':
        raise ApiError(409, 'UNSUPPORTED_SCHEMA', 'Range exploration uses the Parquet release.')
    area = _area(request.app.state.world_areas, query)
    manifest = manifest_for(request.app.state.settings, query.release_id)
    end = query.end_date + timedelta(days=1)
    _check_date_range(manifest, query.start_date, end)
    rows, counts = _range_counts(str(request.app.state.settings.storage.global_release_path),
        manifest['release_id'], area['id'], str(query.start_date), str(end), tuple(area.get('country_codes',())))
    data = statistics(query.start_date, end, rows, counts)
    return data, {**provenance(manifest, area), 'catalog_version':request.app.state.world_areas['version']}, rows


def query_range(query: DateRange, request: Request):
    from app.parquet_data import cell_feature
    data, source, rows = range_result(query, request)
    matches=view_filter(query.bbox)
    visible = [(grid, count) for grid, count in rows if matches(grid)] if query.include_geometry else []
    stop = query.offset + query.page_size
    return {**data, **source, 'type': 'FeatureCollection', 'features': [cell_feature(grid, count)
        for grid, count in visible[query.offset:stop]], 'visible_active_cells': len(visible) if query.include_geometry else None,
        'map_scope': 'viewport' if query.bbox else 'selected_area',
        'next_offset': stop if stop < len(visible) else None}
