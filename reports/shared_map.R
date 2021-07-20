
# todo:
# - higher resolution?

library(rgdal)
library(broom)
library(maptools)
library(ggplot2)

correct_ids = function(map_area) {
  for (i in seq_along(map_area@polygons)) {
    map_area@polygons[[i]]@ID = rownames(map_area@data)[i]
  }
  map_area
}

fix_states = function(shp) {
  # keep mainland states only and move AK and HI closer
  alaska <- correct_ids(shp[shp$STATEFP=='02',])
  alaska <- elide(alaska, rotate=-50)
  alaska <- elide(alaska, scale=max(apply(bbox(alaska), 1, diff)) / 2.3)
  alaska <- elide(alaska, shift=c(-2100000, -2500000))
  proj4string(alaska) <- proj4string(shp)
  # extract, then rotate & shift hawaii
  hawaii <- correct_ids(shp[shp$STATEFP=='15',])
  hawaii <- elide(hawaii, rotate=-35)
  hawaii <- elide(hawaii, shift=c(5400000, -1400000))
  proj4string(hawaii) <- proj4string(shp)
  # remove old states and put new ones back in; note the different order
  # we're also removing puerto rico in this example but you can move it
  # between texas and florida via similar methods to the ones we just used
  states_to_keep = setdiff(shp$STATEFP, c('02','15','60','66','69','72','78'))
  shp <- correct_ids(shp[shp$STATEFP %in% states_to_keep,])
  rbind(shp, alaska, hawaii)
}

shp.state <- readOGR(dsn="/tmp/af/data/misc/shapefiles/cb_2020_us_state_5m/", layer="cb_2020_us_state_5m", verbose=T) %>%
  spTransform(CRS("+proj=laea +lat_0=45 +lon_0=-100 +x_0=0 +y_0=0 +a=6370997 +b=6370997 +units=m +no_defs"))
index.state = data.frame(id=as.character(seq(0, length(shp.state)-1)), fips=shp.state$STATEFP, state_name=shp.state$NAME)
shp.state <- shp.state %>% fix_states() %>% tidy() %>% inner_join(index.state, by='id') 

shp.county <- readOGR(dsn="/tmp/af/data/misc/shapefiles/cb_2020_us_county_5m/", layer="cb_2020_us_county_5m", verbose=T) %>%
  spTransform(CRS("+proj=laea +lat_0=45 +lon_0=-100 +x_0=0 +y_0=0 +a=6370997 +b=6370997 +units=m +no_defs"))
index.county = data.frame(id=as.character(seq(0, length(shp.county)-1)), fips=paste0(shp.county$STATEFP, shp.county$COUNTYFP), state_name=shp.county$STATE_NAME)
shp.county <- shp.county %>% fix_states() %>% tidy() %>% inner_join(index.county, by='id') 

plot_map <- function(data, title='', label='Stat', layer='county') {
  p = ggplot()
  if(layer=='county') {
    shp.plot = shp.county %>% left_join(data, by='fips')
    p = p + geom_polygon(data=shp.plot, aes(x=long, y=lat, group=group, fill=stat)) +
      geom_polygon(data=shp.state, aes(x=long, y=lat, group=group), fill=NA, color='black')
  } else {
    shp.plot = shp.state %>% left_join(data, by='fips')
    p = p + geom_polygon(data=shp.plot, aes(x=long, y=lat, group=group, fill=stat), color='black')
  }
  p + ggtitle(title) +
    scale_fill_viridis_c(label, guide="colorbar", na.value="white") +
    #theme_void() + theme(legend.title=element_blank())
    coord_fixed() +
    theme(
      panel.border=element_blank(),
      panel.grid.major = element_blank(), panel.grid.minor = element_blank(),
      axis.title.x=element_blank(),
      axis.title.y=element_blank(),
      axis.ticks=element_blank(),
      axis.text.y=element_blank(),
      axis.text.x=element_blank(),
      legend.title=element_blank(),
      legend.text=element_text(size=10),
      plot.title = element_text(hjust=0.5),
      #legend.position='none',
      panel.background=element_rect(fill='white'),
      plot.margin=unit(c(0.0, 0.0, 0.0, 0.0), "cm")
    )
}
