
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
  read_csv(paste0(data_folder, "/clean/univaf_locations.csv"),
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
  read_csv(paste0(data_folder, "/clean/univaf_avs_old.csv"),
           col_names=c("id", "checked_time", "last_checked_time", "offset", "availability")) %>%
      inner_join(read_location_data(), by='id')
}

read_availability_slot_data <- function() {
  read_csv(paste0(data_folder, "/clean/univaf_slots_old.csv"),
                  col_names = c('id', 'slot_time', 'hod', 'dow', 'min', 'max')) %>%
  mutate(
    range=as.numeric((max-min)/(60*60)),
    last_time_ahead=as.numeric(difftime(slot_time, max, units='hours')),
    last_time_ahead = ifelse(last_time_ahead < 0, 0, last_time_ahead),
    work_time=ifelse(dow < 5 & hod > 8 & hod < 18, 1, 0),
    type=ifelse(dow > 4, 'weekend', ifelse(hod < 9, 'morning', ifelse(hod >= 18, 'evening', 'workday'))),
    type=factor(type, levels=c('workday','morning','evening','weekend')),
    booked=ifelse(max+hours(2) < slot_time, 1, 0)
  ) %>%
  inner_join(read_location_data() %>% select(-type), by='id') 
}




##
## Read external data sources
##

# read county-level statistics
dcou = left_join(
  # vaccination rate 
  # https://api.covidactnow.org/v2/counties.csv?apiKey=302aad775e824d8e8d60ad1364dd30cb
  read_csv(paste0(data_folder, "/misc/vaccination rates/counties.csv")) %>%
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



# collect vaccination stats from both CDC and CovidAct now, which have different data
make_vax <- function(d1, d2) {
  
  # https://data.cdc.gov/Vaccinations/COVID-19-Vaccinations-in-the-United-States-County/8xkx-amqh
  dvax.cdc.raw = read_csv(paste0(data_folder, "/misc/vaccination rates/COVID-19_Vaccinations_in_the_United_States_County.csv")) %>%
    mutate(date=as.Date(Date, format='%m/%d/%Y')) %>%
    select(date, fips=FIPS, state=Recip_State,
           vax=Administered_Dose1_Recip,            # People with at least one Dose by State of Residence
           old_vax_rate=Administered_Dose1_Pop_Pct  # Percent of Total Pop with at least one Dose by State of Residence
    )
  dvax.cdc = inner_join(
    dvax.cdc.raw %>% filter(date == d1) %>% select(state, fips, vax, old_vax_rate),
    dvax.cdc.raw %>% filter(date == d2) %>% select(state, fips, vax),
    by=c('state', 'fips')) %>%
    mutate(n_vax=vax.y-vax.x) %>%
    select(state, fips, n_vax, old_vax_rate)
  
  # https://api.covidactnow.org/v2/counties.timeseries.csv?apiKey=302aad775e824d8e8d60ad1364dd30cb
  dvax.can.raw = read_csv(paste0(data_folder, "/misc/vaccination rates/counties.timeseries.csv")) %>%
    select(date, fips, state, vax=actuals.vaccinationsCompleted, old_vax_rate=metrics.vaccinationsCompletedRatio)
  dvax.can = inner_join(
    dvax.can.raw %>% filter(date == d1) %>% select(state, fips, vax, old_vax_rate),
    dvax.can.raw %>% filter(date == d2) %>% select(state, fips, vax),
    by=c('state', 'fips')) %>%
    mutate(n_vax=vax.y-vax.x) %>%
    select(state, fips, n_vax, old_vax_rate)
  
  full_join(dvax.cdc , dvax.can, by=c('fips','state')) %>%
    mutate(n_vax=ifelse(!is.na(n_vax.x) & n_vax.x > 0, n_vax.x,
                        ifelse(!is.na(n_vax.y) & n_vax.y > 0, n_vax.y, NA)),
           old_vax_rate=ifelse(!is.na(old_vax_rate.x) & old_vax_rate.x > 0, old_vax_rate.x,
                               ifelse(!is.na(old_vax_rate.y) & old_vax_rate.y > 0, old_vax_rate.y, NA))) %>%
    select(state, fips, n_vax, old_vax_rate)
}



# political leaning
# source : https://dataverse.harvard.edu/file.xhtml?fileId=4819117&version=9.0
# measure is rep/all, not rep/(rep+dem)!
dpol = read_csv(paste0(data_folder, "/misc/political/countypres_2000-2020.csv"), col_types = 'iccccccciicc') %>%
  filter(party=='REPUBLICAN', year==2020, office=='PRESIDENT') %>%
  mutate(fips=str_pad(county_fips, width=5, pad='0'), state=state_po, county=county_name) %>%
  group_by(state, fips) %>%
  summarize(n_votes=max(totalvotes), n_rep_votes=sum(candidatevotes)) %>%
  mutate(p_rep_votes=n_rep_votes/n_votes)


# regression data
make_regression_data <- function(dav, dzip, dvax, dcou, dpol) {
  dav %>% select(-county) %>%
    inner_join(dzip %>% select(zip, fips=county_fips), by='zip') %>%
    group_by(state, fips) %>%
    summarize(
      n_locations=n_distinct(id),
      n_slots=n(),
      n_slots_workday=sum(ifelse(type=='workday', 1, 0)),
      n_slots_weekend=sum(ifelse(type=='weekend', 1, 0)),
      n_slots_evening=sum(ifelse(type=='evening', 1, 0)),
      avg_range=mean(range),
      avg_range_workday=mean(ifelse(type=='workday', range, NA), na.rm=T),
      avg_range_weekend=mean(ifelse(type=='weekend', range, NA), na.rm=T),
      avg_range_evening=mean(ifelse(type=='evening', range, NA), na.rm=T),
      avg_ahead=mean(last_time_ahead),
      avg_ahead_workday=mean(ifelse(type=='workday', last_time_ahead, NA), na.rm=T),
      avg_ahead_weekend=mean(ifelse(type=='weekend', last_time_ahead, NA), na.rm=T),
      avg_ahead_evening=mean(ifelse(type=='evening', last_time_ahead, NA), na.rm=T),
      n_booked=sum(booked)
    ) %>% ungroup() %>%
    left_join(dvax, by=c('fips', 'state')) %>%
    left_join(dcou %>% select(fips, population, vax_rate, hesitant), by='fips') %>%
    left_join(dpol, by=c('fips', 'state')) %>%
    mutate(
      slots_per_person=n_slots/population,
      slots_per_person_workday=n_slots_workday/population,
      slots_per_person_weekend=n_slots_weekend/population,
      slots_per_person_evening=n_slots_evening/population,
      book_per_vax=n_booked/n_vax
    ) %>%
    filter(!is.na(fips)) %>%
    # adjust for coveragae
    mutate(
      slots_per_person = slots_per_person/book_per_vax,
      slots_per_person_workday = slots_per_person_workday/book_per_vax,
      slots_per_person_weekend = slots_per_person_weekend/book_per_vax,
      slots_per_person_evening = slots_per_person_evening/book_per_vax
    ) %>%
    filter(
      is.finite(slots_per_person),
      book_per_vax < 1,   # p 0.92
      book_per_vax > 0.1  # p 0.17
    )
}
