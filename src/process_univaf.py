#
# Script to process USDR's univaf appointment availability data.
# The change log data is downloaded from the S3 folder.
# It processes scraped data by date, iterating over a date-range,
# and writes out both general and slot-level availability data.
#
# We maintain an internal locations database to map the long UUID's
# to small numeric ids. Every time this script runs, it reprocesses
# the locations database.
#
# NOTE: for the availability data checked_time is in UTC.
#       for the slot data, both checked_time and slot_time are in local time.
#
# Usage:
#
#   python process_univaf.py [-h] [-s START_DATE] [-e END_DATE]
#
# Produces:
#
#   locations.csv    - (id, uuid, name, provider, type, address, city,
#                       county, state, zip, lat, lng, timezone)
#   ids.csv          - (external_id, id)
#   avs_{DATE}.csv   - (id, first_checked_time, last_checked_time,
#                       offset, availability)
#   slots_{DATE}.csv - (id, slot_time, first_checked_time, last_checked_time,
#                       offset, availability)
#
# Authors:
#
#   Jan Overgoor - jsovergoor@usdigitalresponse.org
#

import argparse
import csv
import datetime
import dateutil.parser
import json
import ndjson
import os
import pytz
import sys
import traceback
import urllib.request
import us
from glob import glob
from shapely import wkb
# internal
import lib
import univaf_data

# set and make paths
path_raw = univaf_data.DATA_PATH / 'univaf_raw'
path_out = univaf_data.DATA_PATH / 'univaf_clean'
for path in [path_raw, path_out]:
    if not os.path.exists(path):
        os.mkdir(path)

# set global variables
locations = {}
eid_to_id = {}
avs = {}    # { id : [ts_first, ts_last, offset, available] }
slots = {}  # { id : { ts_slot : [ts_first, ts_last, offset, available] }}


def do_date(ds):
    """
    Process a single date.
    """
    global avs, slots
    print("[INFO] doing %s" % ds)

    # open output files
    fn_avs = "%savs_%s.csv" % (path_out, ds)
    f_avs = open(fn_avs, 'w')
    writer_avs = csv.writer(f_avs, delimiter=',', quoting=csv.QUOTE_MINIMAL)
    n_avs = 0
    fn_slots = "%sslots_%s.csv" % (path_out, ds)
    f_slots = open(fn_slots, 'w')
    writer_slots = csv.writer(f_slots, delimiter=',', quoting=csv.QUOTE_MINIMAL)
    n_slots = 0

    # read previous state, if exists
    avs = lib.read_previous_state(path_raw, ds, 'avs')
    slots = lib.read_previous_state(path_raw, ds, 'slots')

    # construct list of files to read
    files = sorted(glob('%savailability_log-%s.ndjson' % (path_raw, ds)))
    for fn in files:

        print("[INFO]   reading " + fn)
        f = open(fn, 'r')
        for row in ndjson.reader(f):
            try:
                # only process rows that have a (new) valid_at field
                if "valid_at" not in row:
                    continue
                # look up the location
                if 'uuid:%s' % row['location_id'] in eid_to_id:
                    sid = 'uuid:%s' % row['location_id']
                elif 'univaf_v1:%s' % row['location_id'] in eid_to_id:
                    sid = 'univaf_v1:%s' % row['location_id']
                elif 'univaf_v0:%s' % row['location_id'] in eid_to_id:
                    sid = 'univaf_v0:%s' % row['location_id']
                else:
                    print('[WARN]     id %s not in the dictionary...' % row['location_id'])
                    continue
                iid = int(eid_to_id[sid])
                loc = locations[iid]

                # skip new locations without change as we don't know their prior state
                if iid not in avs and ("available" not in row or row['available'] is None):
                    continue

                # parse checked_time and convert to UTC if not already
                t = row['valid_at']
                if t[-5:] == '00:00' or t[-1] == 'Z':
                    check_time_utc = datetime.datetime.strptime(t[:19], "%Y-%m-%dT%H:%M:%S")
                else:
                    check_time_utc = dateutil.parser.parse(t).astimezone(pytz.timezone('UTC'))
                check_time_local = check_time_utc.astimezone(pytz.timezone(loc['timezone']))
                offset = int(check_time_local.utcoffset().total_seconds() / (60 * 60))
                check_time = check_time_utc.strftime("%Y-%m-%d %H:%M:%S")  # in UTC

                # if nothing new, just update the last time
                if "available" not in row or row['available'] is None:
                    avs[iid][1] = check_time
                    # update each slot time
                    if iid in slots:
                        for ts in slots[iid].keys():
                            slots[iid][ts][1] = check_time
                    continue

                # compute regular availability count
                availability = None
                if row['available'] in ['YES', 'yes']:
                    if 'available_count' in row:
                        availability = row['available_count']
                    elif ('capacity' in row and row['capacity'] is not None and
                          row['capacity'][0]['available'] not in ['YES','NO']):
                        availability = 0
                        for em in row['capacity']:
                            if 'available_count' in em:
                                availability += em['available_count']
                            elif 'available' in em:
                                availability += em['available']
                            else:
                                raise Exception('No availability counts found...')
                    else:
                        availability = '+'
                elif row['available'] in ['NO', 'no']:
                    availability = 0
                elif row['available'] == 'UNKNOWN':
                    availability = None
                else:
                    availability = None
                    raise Exception('No availability found...')

                # create a new row if the location is new
                if iid not in avs:
                    avs[iid] = [check_time, check_time, offset, availability]
                # if new row but availability didn't change, just update time
                if availability == avs[iid][3]:
                    avs[iid][1] = check_time
                # else, write old row and update new row
                else:
                    writer_avs.writerow([iid] + avs[iid])
                    n_avs += 1
                    avs[iid] = [check_time, check_time, offset, availability]

                # do slots, if the data is there
                if 'slots' in row and row['slots'] is not None:
                    # create a new row if the location is new
                    if iid not in slots:
                        slots[iid] = {}
                    for slot in row['slots']:
                        # compute local offset and UTC time for slot time
                        slot_time_local = datetime.datetime.fromisoformat(slot['start'])
                        slot_time_offset = int(slot_time_local.utcoffset().total_seconds() / (60 * 60))
                        slot_time_utc = slot_time_local.astimezone(pytz.timezone('UTC'))
                        slot_time = slot_time_utc.strftime("%Y-%m-%d %H:%M")  # in UTC
                        # if slot time didn't exist, create
                        if slot_time not in slots[iid]:
                            if slot['available'] == 'YES' and slot_time > check_time:
                                slots[iid][slot_time] = [check_time, check_time, offset]
                            else:
                                continue
                        # if availability didn't change, just update time
                        if slot['available'] == 'YES' and slot_time > check_time:
                            slots[iid][slot_time][1] = check_time
                        # else, write old row and update new row
                        else:
                            writer_slots.writerow([iid, slot_time] + slots[iid][slot_time])
                            n_slots += 1
                            del slots[iid][slot_time]
                    # assume that slots for which we saw no availaiblity in last update are not available anymore
                    for slot_time in list(slots[iid].keys()):
                        if slots[iid][slot_time][1] != check_time:
                            writer_slots.writerow([iid, slot_time] + slots[iid][slot_time])
                            n_slots += 1
                            del slots[iid][slot_time]

            except Exception as e:
                print("[ERROR] ", sys.exc_info())
                traceback.print_exc()
                print("Problem data: ")
                print(lib.pp(row))
                exit()
        f.close()

    # write unclosed records
    for iid, row in avs.items():
        writer_avs.writerow([iid] + row)
        n_avs += 1
    for iid, tmp_row in slots.items():
        for slot_time, row in tmp_row.items():
            writer_slots.writerow([iid, slot_time] + row)
            n_slots += 1

    # wrap up
    f_avs.close()
    f_slots.close()
    print("[INFO]   wrote %d availability records to %s" % (n_avs, fn_avs))
    print("[INFO]   wrote %d slot records to %s" % (n_slots, fn_slots))
    # write current state for the next day
    next_day = lib.add_days(ds, 1)
    with open(path_raw + 'state_%s_avs.json' % next_day, 'w') as f:
        json.dump(avs, f)
    with open(path_raw + 'state_%s_slots.json' % next_day, 'w') as f:
        json.dump(slots, f)


def process_locations(path_out):
    """
    Process the latest provider_locations and external_ids log files.
    """
    # read zip map
    zipmap = lib.read_zipmap()
    # read 'new' locations
    path_loc = glob(path_raw + 'provider_locations-*.ndjson')[-1]
    with open(path_loc, 'r') as f:
        new_locations = ndjson.load(f)
    for row in new_locations:
        # grab internal numeric id, or make one
        sid = 'uuid:%s' % row['id']
        if sid in eid_to_id:
            iid = eid_to_id[sid]
        else:
            iid = lib.hash(row['id'])
            eid_to_id[sid] = iid
        # set fields to None by default
        [uuid, name, provider, loctype, address, city, county,
         state, zip, lat, lng, tz] = [None] * 12
        # extract fields
        uuid = row['id']
        # TODO: if NOT there, then should look up?
        if 'name' in row and row['name'] is not None:
            name = row['name'].title()
        if 'provider' in row and row['provider'] is not None:
            provider = row['provider'].lower()
            if provider == 'rite_aid':
                provider = 'riteaid'
        if 'location_type' in row and row['location_type'] is not None:
            loctype = row['location_type'].lower()
        if 'city' in row and row['city'] is not None:
            city = row['city'].title()
        if 'county' in row and row['county'] is not None:
            county = row['county'].title()
        if 'state' in row and row['state'] is not None:
            state = row['state'].upper()
        if 'postal_code' in row and row['postal_code'] is not None:
            # NOTE - this throws away information after first 5 digits
            zip = "%05d" % int(row['postal_code'][:5])
        # take county from VS zipmap
        if zip is not None and county is None and zip in zipmap:
            county = zipmap[zip][2]
        # process addres
        if 'address_lines' in row and row['address_lines'] is not None:
            # NOTE - length is never larger than 1
            address = ','.join(row['address_lines'])
            # fix end on ,
            if address[-1] == ',':
                address = address[:-1]
        # fix address issue for some NJ listings
        if ', NJ' in address:
            address = address.split(', ')[0]
            if zip is not None:
                city = zipmap[zip][1]
            # still has city in the address..
        # extract local timezone
        if 'time_zone' in row and row['time_zone'] is not None:
            timezone = row['time_zone']
        elif zip is not None:
            zip = "%05d" % int(row['postal_code'][:5])
            timezone = zipmap[zip][0]
        elif state is not None:
            timezone = us.states.lookup(row['state']).time_zones[0]
        # extract position
        if ('position' in row and row['position'] is not None):
            # original format was dictionary
            if type(row['position']) == dict:
                if 'latitude' in row['position']:
                    lat = row['position']['latitude']
                if 'longitude' in row['position']:
                    lng = row['position']['longitude']
            # else, assume WKB hex
            else:
                (lng, lat) = wkb.loads(bytes.fromhex(row['position'])).coords[0]
        # insert row
        locations[iid] = {
            'uuid': uuid,
            'name': name,
            'provider': provider,
            'type': loctype,
            'address': address,
            'city': city,
            'county': county,
            'state': state,
            'zip': zip,
            'lat': lat,
            'lng': lng,
            'timezone': timezone
        }

    # read 'new' external_id to uuid mapping
    path_ids = glob(path_raw + 'external_ids-*.ndjson')[-1]
    with open(path_ids, 'r') as f:
        eid_to_uuid = {}
        for x in ndjson.load(f):
            eid_to_uuid['%s:%s' % (x['system'], x['value'])] = x['provider_location_id']
    # insert into external_id to iid mapping
    for eid, uuid in eid_to_uuid.items():
        uuid = 'uuid:' + uuid
        eid = lib.scrub_external_ids([eid])[0]
        if uuid not in eid_to_id:
            print("[WARN] uuid %s not in eid_to_id" % uuid)
            continue
        eid_to_id[eid] = eid_to_id[uuid]
    # write updated location files
    lib.write_locations(locations, path_out + 'univaf_locations.csv')
    lib.write_external_ids(eid_to_id, path_out + 'univaf_ids.csv')
    return (locations, eid_to_id)


def download_files(ds, types=None):
    """
    Download the files, if they don't already exist.
    """
    types = types or ['availability_log', 'external_ids', 'provider_locations']
    for type in types:
        univaf_data.download_log_file(type, ds)


if __name__ == "__main__":
    import lib_cli
    args = lib_cli.create_agument_parser().parse_args()
    dates = lib_cli.get_dates_in_range(args.start_date, args.end_date)

    print("[INFO] doing these dates: [%s]" % ', '.join(dates))
    # download files
    for date in dates:
        download_files(date)
    # process latest locations file
    (locations, eid_to_id) = process_locations(path_out)
    # iterate over days
    for date in dates:
        do_date(date)
    # aggregate slot data over multiple days
    fn_slots = lib.path_root + '/univaf_clean/univaf_slots.csv'
    lib.aggregate_slots(path_out, fn_slots)
