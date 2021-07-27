# Appointment Availability Data Insights

This repo contains code to work with USDR's [UNIVAF](http://getmyvax.org/docs/) appointment data, and some analysis done using this data.


## Processing Code

The data processing code is written in Python 3. The pipeliness for [UNIVAF](http://getmyvax.org/docs/) and [VaccineSpotter](https://www.vaccinespotter.org/api/#historical) are very similar, but slightly different. In either case, the code downloads the raw data files if necessary, processes them day by day, and aggregates records to combine intervals that span more than a day. Raw data is stored in `./data/{SOURCE}_raw/` and processed data in `./data/{SOURCE}_clean/`.

The intstructions for how to run the scrips are included in each script respectively, but the general format is the same:

```
python process_{SOURCE}.py -s {START_DATE} -e {END_DATE}
```

One major difference is how locations are processed. UNIVAF maintains a separate database for provider locations, so the last file is always the one to use. For VaccineSpotter, the location information comes from the availability records, so we maintain a location database that gets updated every time a new row comes in.


## Analysis Code

The analysis code lives in `./reports` and is all written in R/RMarkdown. Here is a list of libraries to install to reproduce everything:

```
install.packages(c('tidyverse', 'scales', 'lubridate', 'rgdal', 'broom', 'maptools'))
```

Each report is checked-in as the `.Rmd` file containing the source code, and the `.html` file which has the rendered content. To reproduce everything, you can re-knit the `.Rmd` reports from RStudio or from the command line like so:

```
Rscript -e "rmarkdown::render('./reports/state_AK.Rmd')"
```

Here is an index of the rendered analyses:

* [Coverage](https://raw.githack.com/usdigitalresponse/appointment-data-insights/main/reports/coverage.html)
* State reports:
    - [Alaska](
https://raw.githack.com/usdigitalresponse/appointment-data-insights/main/reports/state_AK.html)
    - [Colorado](
https://raw.githack.com/usdigitalresponse/appointment-data-insights/main/reports/state_CO.html)
    - [New Jersey](
https://raw.githack.com/usdigitalresponse/appointment-data-insights/main/reports/state_NJ.html)
    - [New York](
https://raw.githack.com/usdigitalresponse/appointment-data-insights/main/reports/state_NY.html)
    - [Pennsylvania](
https://raw.githack.com/usdigitalresponse/appointment-data-insights/main/reports/state_PA.html)
    - [Washington](
https://raw.githack.com/usdigitalresponse/appointment-data-insights/main/reports/state_WA.html)
* [Univaf Sandbox](
https://raw.githack.com/usdigitalresponse/appointment-data-insights/main/reports/univaf_sandbox.html)
* [VaccineSpotter Sandbox](
https://raw.githack.com/usdigitalresponse/appointment-data-insights/main/reports/vs_sandbox.html)
* [Content for blogpost](
https://raw.githack.com/usdigitalresponse/appointment-data-insights/main/reports/blogpost.html)
