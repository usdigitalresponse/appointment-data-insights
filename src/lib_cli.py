import argparse
import datetime
import dateutil.parser


def cli_date(text):
    """Parse a timestamp string"""
    return dateutil.parser.parse(text).date()


def create_agument_parser(**kwargs):
    """Create an argument parser with basic start/end date options."""
    parser = argparse.ArgumentParser(**kwargs)
    parser.add_argument('-s', '--start_date',
                        help="First date to process (format: YYYY-MM-DD)",
                        type=cli_date, metavar='DATE', required=True)
    parser.add_argument('-e', '--end_date',
                        help="Last date to process (format: YYYY-MM-DD)",
                        type=cli_date, metavar='DATE')
    return parser


def get_dates_in_range(start_date, end_date=None):
    """
    Given a start and end datetime, create a list of date strings representing
    every date between them, including the start and end dates.

    Example
    -------
    >>> get_dates_in_range(datetime(2022, 1, 1), datetime(2022, 1, 3))
    ['2022-01-01', '2022-01-02', '2022-01-03']
    """
    if end_date is None:
        end_date = start_date

    n = (end_date - start_date).days + 1
    dates = [start_date + datetime.timedelta(days=x) for x in range(n)]
    dates = sorted([x.strftime("%Y-%m-%d") for x in dates])
    if len(dates) < 1:
        print("[ERROR] date range has no elements")
        exit()

    return dates