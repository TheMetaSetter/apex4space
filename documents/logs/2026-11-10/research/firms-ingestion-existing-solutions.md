# Existing FIRMS ingestion tools

The [preprocessing notebook](../../../../time-series-api/notebooks/preprocess_tabular.ipynb) allows a Python function or class that loads raw data in batches. Cleaning and integration follow data preparation. This review covers FIRMS active-fire detections, which are tabular records.

## FIRMS clients and pipelines

| Tool | Fit and trade-off |
| --- | --- |
| **firms-client** | Closest standalone CLI. Its `firms area` command queries by source and bounding box, splits longer date ranges and retries transient failures. Area results are uncached. The archive command caches yearly CSVs locally. The documented parser takes CSV text and returns a list, so the documented interface gives no bounded-memory guarantee. [Maintainer documentation](https://github.com/agent-engineering-studio/firms-client) |
| **real-time-sources FIRMS feeder** | Closest continuous ingestion match. Polls all three VIIRS NRT sources and MODIS NRT by default, offers a one-cycle mode and publishes a CloudEvent per detection to Kafka, MQTT or AMQP. Persists dedupe state in a JSON file. A remote broker keeps event storage off the client, but adds a service dependency. [Container docs](https://github.com/clemensv/real-time-sources/blob/main/feeders/nasa-firms/CONTAINER.md) |
| **NASA FIRMS Streaming Data Pipeline** | Demonstrates replay from PostgreSQL staging and upserts through Kafka into PostGIS. MODIS and backfill are listed as future work. Database retention is a documented gap. [Project README](https://github.com/ADN004/nasa-firms-streaming-pipeline) |
| **geospace_data FIRMS tools** | VIIRS and MODIS CLI downloader with a separate file-based processing command. A reference for CLI scope, with local files as the handoff. [FIRMS docs](https://github.com/labgeea/geospace_data/blob/main/firms/firms_README.md) |
| **FireDataForge** | Fetches VIIRS SP or NRT for each fire's bounding box and dates, uses windows of up to five days and deduplicates results. Caches per-event CSVs locally. [Dataset docs](https://github.com/xiazeyu/FireDataForge#firms--viirs-active-fire-dataset) |

## Reusable components

- **curl and Apache Arrow** cover the smallest local path. curl can pipe a single HTTP CSV response to stdout. Arrow's `open_csv()` yields record batches for Python preprocessing. Once a partial response reaches a pipe, retrying it can duplicate output. [curl manual](https://curl.se/docs/manpage.html), [Arrow CSV docs](https://arrow.apache.org/docs/python/csv.html)
- **Singer and Meltano** supply a CLI protocol for schema, records and state over stdout. A FIRMS adapter still needs to decide which windows to request and when to advance state. [Singer spec](https://hub.meltano.com/singer/spec/)
- **DuckDB** can query HTTP CSV without a separate download file. CSV scans usually transfer the entire response. Remote Parquet supports partial reads. [DuckDB HTTP docs](https://duckdb.org/docs/preview/core_extensions/httpfs/https)

## NASA source constraints

FIRMS Area API is a finite CSV request per source, bounding box or world, and 1–5 day window. Continuous intake comes from polling. NASA publishes a limit of 5,000 transactions per ten minutes per MAP_KEY, with larger queries potentially costing more than one transaction. [NASA Area API](https://firms.modaps.eosdis.nasa.gov/api/area/)

NASA offers Archive Download for older data. The archive replaces near-real-time data (NRT) with standard processing (SP) when available, so it may differ from the data a live poll originally returned. NASA also offers recent daily text files with Earthdata authentication. [FIRMS archive](https://firms.modaps.eosdis.nasa.gov/download/), [LANCE daily files](https://nrt4.modaps.eosdis.nasa.gov/archive/FIRMS/)

The notebook can consume bounded batches without a complete local copy. Direct piping fits immediate preprocessing. A durable remote sink fits replay or preprocessing that runs later. These are conclusions from the notebook and public docs. Live FIRMS calls, memory bounds and disk usage were not measured.
