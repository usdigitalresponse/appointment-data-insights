from collections import defaultdict
import gzip
import json
import os
import re
from tqdm import tqdm


FILE_DATE_PATTERN = re.compile(r'-(\d\d\d\d-\d\d-\d\d)\.')


def read_json_lines(filepath, compressed=None):
    if compressed is None:
        compressed = filepath.endswith('.gz')
    
    context = gzip.open(filepath, 'rt') if compressed else open(filepath)
    with context as f:
        for line in f:
            if line and line != '\n':
                yield json.loads(line)


def create_location_listings(location_file, id_file):
    locations = {}
    location_lookup = {}
    for location in read_json_lines(location_file):
        value = defaultdict(lambda: 0)
        locations[location['id']] = value
        location_lookup[location['id']] = value


    for row in read_json_lines(id_file):
        if row['system'].startswith('univaf_'):
            # print(f"Adding merged ID: {row['value']}")
            location = locations[row['provider_location_id']]
            location_lookup[row['value']] = location
    
    return locations, location_lookup


def count_capacity_slots(entry):
    count = entry.get('available_count', 0) + entry.get('unavailable_count', 0)
    # If no counts, be conservative and assume this entry represents 1 slot.
    if count == 0:
        count = 1
    return count


def count_slots_by_day_in_locations(location_lookup, log_files):
    for filepath in log_files:
        file_name = os.path.basename(filepath)
        file_date = FILE_DATE_PATTERN.search(filepath).group(1)
        lines = tqdm(read_json_lines(filepath),
                     mininterval=2,
                     unit='rows',
                     unit_scale=True,
                     desc=f'Reading {file_name}')
        for row in lines:
            location = location_lookup.get(row['location_id'])
            if location is None:
                tqdm.write(f"WARN: no matching row for: {row['location_id']}")

            capacity = row.get('capacity')
            slots = row.get('slots')
            if capacity:
                for entry in capacity:
                    day = entry['date']
                    count = count_capacity_slots(entry)
                    location[day] = max(location[day], count)
                    # Be extra careful
                    if count > 5_000:
                        tqdm.write(f"WARN: location {row['location_id']} has {count} slots on {day}")
            elif slots:
                count_by_day = defaultdict(lambda: 0)
                for entry in slots:
                    day = entry['start'][0:10]
                    count = count_capacity_slots(entry)
                    count_by_day[day] += count
                for day, count in count_by_day.items():
                    location[day] = max(location[day], count)
                    # Be extra careful
                    if count > 5_000:
                        tqdm.write(f"WARN: location {row['location_id']} has {count} slots on {day}")
            elif 'available' in row:
                # If there's no day- or slot-level data, be conservative and
                # count 1 slot for the current current day of the report.
                # ONLY do this if we actual got *some* info about availability
                # (i.e. 'available' is filled in) -- Ignore records that
                # represent "no change" since that data will get filled in from
                # reading other records.
                location[file_date] = max(location[file_date], 1)


def sum_slots_by_day(locations):
    days = defaultdict(lambda: 0)
    for counts in locations.values():
        for day, count in counts.items():
            days[day] += count
    
    result = []
    total = 0
    for day in sorted(days.keys()):
        total += days[day]
        result.append({'date': day, 'count': days[day], 'total': total})
    
    return result


if __name__ == '__main__':
    import lib_cli
    args = lib_cli.create_agument_parser().parse_args()
    dates = lib_cli.get_dates_in_range(args.start_date, args.end_date)

    location_file = f'../data/univaf_raw/provider_locations-{dates[-1]}.ndjson'
    id_file = f'../data/univaf_raw/external_ids-{dates[-1]}.ndjson'
    log_files = [f'../data/univaf_raw/availability_log-{dt}.ndjson.gz' for dt in dates]

    locations, location_lookup = create_location_listings(location_file, id_file)
    count_slots_by_day_in_locations(location_lookup, log_files)

    sums = sum_slots_by_day(locations)
    for day in sums:
        print(f'{day["date"]}: {day["count"]:>7,d} (total: {day["total"]:>11,d})')
