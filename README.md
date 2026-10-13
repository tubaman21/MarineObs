# Great Lakes Marine Surface Observations Placefile Generator

A Python-based telemetry generator that fetches real-time marine surface observations across the Great Lakes Basin (Lakes Superior to Ontario) and compiles them into an automated, time-series looping GRLevelX placefile.

## Features

- **Multi-Source Ingestion**:
  - **Synoptic Data Networks**: Fixed NDBC buoys, NOS-WLON tide gauges, C-MAN, and GLOS land/fixed stations.
  - **NWS Duluth Marine Data**: Real-time VOS (Voluntary Observing Ship) freighter and vessel reports across the Great Lakes.
- **Dynamic Time-Series Looping**: Calculates continuous `TimeRange` intervals up to 4 hours back, ensuring smooth animation without early drop-offs or double plotting during radar loops in GR2Analyst or GRLevel3.
- **Rich Display Parameters**:
  - Plots wind barbs, sky cover, surface air temperature (°F), dewpoint (°F), and altimeter/SLP (mb).
  - Highlights peak wind gusts and marine gale/storm force thresholds with color-coded text.
  - Interactive hover text featuring observation time, station/vessel ID, pressure tendency, peak 1-hour gusts, and visibility.

## Prerequisites

- Python 3.8+
- `requests` library

```bash
pip install requests
Environment Setup
You must set a valid Synoptic Networks API token as an environment variable before running the script:

Bash
export SYNOPTIC_API_TOKEN="your_synoptic_api_token_here"
On Windows (Command Prompt):

DOS
set SYNOPTIC_API_TOKEN=your_synoptic_api_token_here
On Windows (PowerShell):

PowerShell
$env:SYNOPTIC_API_TOKEN="your_synoptic_api_token_here"
Usage
Run the generator manually or set up a recurring cron job / GitHub Action (recommended refresh interval: 5 minutes):

Bash
python marine_generator.py
Upon execution, the script generates placefiles/marine_observations.txt.

GRLevelX Configuration
In GR2Analyst, GRLevel3, or Gibson Ridge software, open Windows > Placefiles.

Add the URL pointing to your hosted marine_observations.txt file.

Set the refresh rate to 5 minutes.

License
This project is licensed under the MIT License.
