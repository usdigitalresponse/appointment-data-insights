from collections import defaultdict
import concurrent.futures
from datetime import date
import functools
import gzip
import json
import os
from pathlib import Path
import re


FILE_DATE_PATTERN = re.compile(r'-(\d\d\d\d-\d\d-\d\d)\.')


def read_json_lines(filepath, compressed=None):
    if compressed is None:
        compressed = str(filepath).endswith('.gz')

    context = gzip.open(filepath, 'rt') if compressed else open(filepath)
    with context as f:
        for line in f:
            if line and line != '\n':
                yield json.loads(line)


def deduplicate_locations(data, id_file):
    """
    Identify duplicate locations using a recent dump of the ``external_ids``
    table and combine slot counts from locations that are duplicates. (This is
    important because historical logs will contain reports for different
    location IDs that we later learned were duplicates.)
    """
    clean = {}
    lookup = {}
    for row in read_json_lines(id_file):
        location_id = row['provider_location_id']
        if not (location_id in lookup):
            clean[location_id] = defaultdict(lambda: 0)
            lookup[location_id] = clean[location_id]
        if row['system'].startswith('univaf_'):
            lookup[row['value']] = clean[location_id]

    for location_id, dates in data.items():
        clean_entry = lookup.get(location_id)
        if clean_entry is None:
            print(f"WARN: no matching row for: {location_id}")
            clean_entry = defaultdict(lambda: 0)
            lookup[location_id] = clean_entry
            clean[location_id] = clean_entry

        for day, count in dates.items():
            clean_entry[day] = max(clean_entry[day], count)

    return clean


def count_capacity_slots(entry):
    count = entry.get('available_count', 0) + entry.get('unavailable_count', 0)
    # If no counts, be conservative and assume this entry represents 1 slot.
    if count == 0:
        count = 1
    return count


def summarize_slots(records, default_date=None):
    """
    Given an iterable of availability log records, count the total tracked slots
    per location and day. Returns a dict where keys are location IDs and values
    are a dict where keys are date strings (e.g. "2021-11-01") and values are
    integers:

        {
          'location_id': {'2021-11-01': 15, '2021-11-02': 13, ...},
          'location_id': {'2021-11-01': 28, '2021-11-02': 10, ...},
          ...
        }
    """
    locations = defaultdict(lambda: defaultdict(lambda: 0))
    for row in records:
        location_id = row['location_id']
        location = locations[location_id]
        capacity = row.get('capacity')
        slots = row.get('slots')
        if capacity:
            for entry in capacity:
                day = entry['date']
                count = count_capacity_slots(entry)
                location[day] = max(location[day], count)
                # Be extra careful
                if count > 5_000:
                    print(f"WARN: location {location_id} has {count} slots on {day}")
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
                    print(f"WARN: location {location_id} has {count} slots on {day}")
        elif 'available' in row:
            # If there's no day- or slot-level data, be conservative and
            # count 1 slot for the current current day of the report.
            # ONLY do this if we actual got *some* info about availability
            # (i.e. 'available' is filled in) -- Ignore records that
            # represent "no change" since that data will get filled in from
            # reading other records.
            day = default_date or entry['valid_at'][0:10]
            location[day] = max(location[day], 1)

    return locations


def summarize_slots_in_file(file_path, cache_directory):
    cache_path = cache_directory / f'{file_path.name}.json'
    if cache_path.exists():
        print(f'Reading cache: {cache_path}...')
        with cache_path.open(encoding='utf-8') as f:
            return json.load(f)
    else:
        print(f'Reading {file_path}...')
        file_date = FILE_DATE_PATTERN.search(file_path.name).group(1)
        result = summarize_slots(read_json_lines(file_path), file_date)

        # Cache it for later use.
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with cache_path.open('w', encoding='utf-8') as f:
            json.dump(result, f, separators=(',', ':'), ensure_ascii=False)

        # Return a plain old dict of dicts so it's pickle-able.
        return {location_id: dict(dates)
                for location_id, dates in result.items()}


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
    parser = lib_cli.create_agument_parser()
    parser.add_argument('--reference_date',
                        help="Date of datafiles to use for deduplication, location attributes, etc.",
                        type=lib_cli.cli_date, metavar='DATE')
    args = parser.parse_args()
    dates = lib_cli.get_dates_in_range(args.start_date, args.end_date)

    data_path = Path('../data/univaf_raw')
    cache_path = Path('../data/univaf_counts')

    # TODO: should this be yesterday, instead of the last date of the sequence?
    reference_date = args.reference_date or args.end_date or args.start_date
    id_file = data_path / f'external_ids-{reference_date}.ndjson.gz'
    location_file = data_path / f'provider_locations-{reference_date}.ndjson.gz'
    log_files = [data_path / f'availability_log-{dt}.ndjson.gz' for dt in dates]

    # FIXME: this needs to automatically download the relevant files.
    # See `download_files()` in process_univaf.py.

    # Rite Aid's API sent incorrect (and very large) numbers of slots for some
    # locations from 2021-09-09 through 2021-11-17 (when it broke). We want to
    # identify these bad values and replace them with something more realistic.
    rite_aid_bad_days = frozenset(lib_cli.get_dates_in_range(date(2021, 9, 9),
                                                             date(2021, 11, 17)))
    rite_aid_ids = frozenset((location['id']
                              for location in read_json_lines(location_file)
                              if location['provider'] == 'rite_aid'))
    def clean_count(checked_date, location_id, count):
        # Substitute the median number of slots for locations with anomalously
        # high slot counts. (Calculated from the month after fixing issues.)
        if (
            checked_date in rite_aid_bad_days and
            location_id in rite_aid_ids and
            count > 500
        ):
            return 13
        return count
    
    # Process each file, then combine the results into a dict of slot counts by
    # day by location ID:
    #   {
    #     'location_id': {'2021-11-01': 15, '2021-11-02': 13, ...},
    #     'location_id': {'2021-11-01': 28, '2021-11-02': 10, ...},
    #     ...
    #   }
    locations = defaultdict(lambda: defaultdict(lambda: 0))
    with concurrent.futures.ProcessPoolExecutor() as executor:
        summarizer = functools.partial(summarize_slots_in_file, cache_directory=cache_path)
        for file_path, summary in zip(log_files, executor.map(summarizer, log_files)):
            file_date = FILE_DATE_PATTERN.search(file_path.name).group(1)
            for location_id, dates in summary.items():
                for day, count in dates.items():
                    # Modify counts that are known to be bad data.
                    count = clean_count(file_date, location_id, count)
                    locations[location_id][day] = max(locations[location_id][day], count)

    locations = deduplicate_locations(locations, id_file)

    sums = sum_slots_by_day(locations)
    for day in sums:
        print(f'{day["date"]}: {day["count"]:>9,d} (total: {day["total"]:>11,d})')

    # # Break down counts by provider on each day.
    # locations_data = {}
    # for location in read_json_lines(location_file):
    #     locations_data[location['id']] = location
    
    # days = defaultdict(lambda: defaultdict(lambda: 0))
    # for location_id, counts in locations.items():
    #     location_data = locations_data[location_id]
    #     for day, count in counts.items():
    #         days[day][location_data['provider'] or ''] += count

    # for day in sorted(days.keys()):
    #     total = sum(days[day].values())
    #     print(f'{day}: {total:>9,d}')
    #     for provider in sorted(days[day].keys()):
    #         print(f'    {provider:.<32}.{days[day][provider]:.>9,d}')
