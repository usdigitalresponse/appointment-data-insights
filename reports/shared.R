
library(tidyverse)
library(scales)
library(lubridate)

data_folder = '../../data'


##
## Shared functions
##

my_theme <- function(base_size=11) {
  # Set the base size
  theme_bw(base_size=base_size) +
    theme(
      # Center title
      plot.title = element_text(hjust=0.5),
      # Make the background white, with open top-right
      panel.grid.major=element_blank(),
      panel.grid.minor=element_blank(),
      axis.line=element_line(colour="black"),
      panel.border=element_blank(),
      panel.background=element_blank(),
      # Minimize margins
      plot.margin=unit(c(0.2, 0.2, 0.2, 0.2), "cm"),
      panel.spacing=unit(0.25, "lines"),
      # Tiny space between axis labels and tick labels
      axis.title.x=element_text(margin=ggplot2::margin(t=6.0)),
      axis.title.y=element_text(margin=ggplot2::margin(r=6.0)),
      # Simplify the legend
      legend.title=element_blank(),
      legend.key=element_blank(),
      legend.background=element_rect(fill='transparent')
    )
}

big_numbers <- Vectorize(function(x, force_k=T, force_m=F){
  ifelse(x==0, 0,
    ifelse(force_k, sprintf("%.1f", x/1000), 
    ifelse(force_m, sprintf("%.1f", x/1000000), 
    ifelse(x > 1000000, sprintf("%.1fM", x/1000000), 
    ifelse(x > 1000, sprintf("%.1fk", x/1000), x))))) -> ret
  ret[is.na(x)] <- NA
  names(ret) <- names(x)
  ret
})


##
## Read univaf data
## 


read_location_data <- function() {
  read_csv(paste0(data_folder, "/clean/locations_univaf.csv"),
           col_types='dcccccccccddc') %>%
    mutate(provider=recode(provider,
                           `albertsons acme`="albertsons_acme",
                           `sams_club sams_club`="sams_club",
                           `weis weis`="weis",
                           `walmart walmart`="walmart",
                           `health_mart health_mart`="health_mart"
    ))
}

read_availability_data <- function() {
  read_csv(paste0(data_folder, "/clean/availabilities_univaf.csv"),
           col_names=c("id", "checked_time", "offset", "availability"))
}

read_availability_slot_data <- function() {
  read_csv(paste0(data_folder, "/clean/availabilities_slots_grouped_univaf.csv"),
                  col_names = c('id', 'slot_time', 'hod', 'dow', 'n', 'min', 'max')) %>%
  mutate(
    range=as.numeric((max-min)/(60*60)),
    last_time_ahead=as.numeric((slot_time-max)/(60*60)),
    work_time=ifelse(dow < 5 & hod > 8 & hod < 18, 1, 0),
    booked=ifelse(max+hours(2) > slot_time, 1, 0)
  )
}




##
## Read external data sources
##

# read county-level statistics
dcou = left_join(
  # vaccination rate 
  # https://api.covidactnow.org/v2/counties.csv?apiKey=302aad775e824d8e8d60ad1364dd30cb
  read_csv(paste0(data_folder, "/misc/vaccination rates/covic_act_now-counties_20210605.csv")) %>%
    select(fips, state, county, population, vax_rate=metrics.vaccinationsCompletedRatio),
  # hesitancy rate
  read_csv(paste0(data_folder, '/misc/Vaccine_Hesitancy_for_COVID-19__County_and_local_estimates_wogeo.csv')) %>%
    mutate(fips=str_pad(`FIPS Code`, width=5, side='left', pad=0)) %>%
    select(fips, hesitant=`Estimated hesitant`),
  by='fips')

# zip data from Nick Muerter
dvs = read_csv(paste0(data_folder, "/misc/vaccinespotter-zipdump.csv"), col_types='cccccddc') %>%
      left_join(read_csv(paste0(data_folder, "/misc/zcta/state_fips.csv"), col_types = 'ccc'), by='state_code') %>%
      mutate(county_fips=paste0(state_fips, county_code)) %>%
      select(state=state_code, zip=postal_code, county=county_name, county_fips)

# read ACS demographics
dacs = read_csv(paste0(data_folder, "/misc/zcta/ACSDP5Y2019.DP05_2021-06-04T174017/ACSDP5Y2019.DP05_data_with_overlays_2021-06-04T103348.csv")) %>%
  slice(2:n()) %>%
  mutate(zip=str_sub(NAME, 7, 11),
         total=as.numeric(DP05_0033E),
         p_male=as.numeric(DP05_0002E)/total,
         p_black=as.numeric(DP05_0065E)/total) %>%
  select(zip, total, p_male, p_black)

# read SVI statistics
dsvi <- read_csv(paste0(data_folder, "/misc/svi_censustract.csv")) %>%
  select(state=ST_ABBR, county=COUNTY, fips=STCNTY, tract=FIPS,
         pop=E_TOTPOP, svi_socioeconomic=RPL_THEME1, svi_household=RPL_THEME2, svi_minority=RPL_THEME3, svi_housing=RPL_THEME4) %>%
  # zip to tract map
  inner_join(read_csv(paste0(data_folder, "/misc/zcta/ZIP_TRACT_032021.csv"), col_types='ccccdddd') %>%
               select(zip=ZIP, tract=TRACT, p_res=RES_RATIO),
             by='tract') %>%
  group_by(zip) %>% summarize(
    pop=sum(pop),
    svi_socioeconomic= sum(ifelse(svi_socioeconomic < 0, 0, svi_socioeconomic) * p_res),
    svi_household=     sum(ifelse(svi_household < 0, 0, svi_household) * p_res),
    svi_minority=      sum(ifelse(svi_minority < 0, 0, svi_minority) * p_res),
    svi_housing=       sum(ifelse(svi_housing < 0, 0, svi_housing) * p_res))

dzip = dvs %>% left_join(dacs, by='zip') %>% left_join(dsvi, by='zip')

# time series of vaccinations
# https://api.covidactnow.org/v2/states.timeseries.csv?apiKey=302aad775e824d8e8d60ad1364dd30cb
dvax = read_csv(paste0(data_folder, "/misc/vaccination rates/states.timeseries.csv")) %>%
  select(date, fips, state, vax=actuals.vaccinationsCompleted)
dvax = inner_join(
  dvax %>% filter(date == '2021-05-24') %>% select(state, vax),
  dvax %>% filter(date == '2021-06-06') %>% select(state, vax),
  by='state') %>%
  mutate(n_vax=vax.y-vax.x) %>%
  select(state, n_vax)
