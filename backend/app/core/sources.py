"""Registry of every external data source (seeded into data_source_status)."""
SOURCES = [
    dict(source_key="tomtom_traffic", display_name="TomTom Traffic Flow", expected_interval_min=15,
         attribution="Traffic data © TomTom", license_url="https://developer.tomtom.com/legal"),
    dict(source_key="openaq", display_name="OpenAQ v3 (CPCB/OSPCB air quality)", expected_interval_min=60,
         attribution="CPCB/OSPCB monitoring data via OpenAQ; per-station licenses apply", license_url="https://docs.openaq.org/about/about"),
    dict(source_key="open_meteo", display_name="Open-Meteo (weather)", expected_interval_min=60,
         attribution="Weather data by Open-Meteo.com (CC BY 4.0, non-commercial use)", license_url="https://open-meteo.com/en/license"),
    dict(source_key="waste_import", display_name="Waste records (manual/CSV import)", expected_interval_min=None,
         attribution="Imported by administrators or simulated for demonstration", license_url=""),
]
