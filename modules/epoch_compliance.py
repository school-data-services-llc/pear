import requests
import pandas as pd
from datetime import datetime, timedelta
import time
import logging
from zoneinfo import ZoneInfo


def resolve_date_range(start_date: datetime):
    """Normalize start_date to America/Chicago and return (start_date, end_date=now)."""
    tz = ZoneInfo("America/Chicago")
    if start_date.tzinfo is None:
        start_date = start_date.replace(tzinfo=tz)
    else:
        start_date = start_date.astimezone(tz)
    return start_date, datetime.now(tz)


def is_date_range_active(start_date: datetime) -> bool:
    start_date, end_date = resolve_date_range(start_date)
    return start_date <= end_date


def filter_frame_to_date_range(df, date_col, start_date, end_date=None):
    """Keep rows whose date_col falls within [start_date, end_date]."""
    if df is None or df.empty:
        return df
    if date_col not in df.columns:
        logging.warning(
            f"No '{date_col}' column to filter by date range; returning unfiltered frame"
        )
        return df

    if end_date is None:
        start_date, end_date = resolve_date_range(start_date)

    col = pd.to_datetime(df[date_col], utc=True, errors="coerce")
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    if start.tzinfo is None:
        start = start.tz_localize("America/Chicago")
    if end.tzinfo is None:
        end = end.tz_localize("America/Chicago")
    start = start.tz_convert("UTC")
    end = end.tz_convert("UTC")

    filtered = df.loc[(col >= start) & (col <= end)].copy()
    logging.info(
        f"Date filter on {date_col}: {len(df)} -> {len(filtered)} rows "
        f"(start={start_date}, end={end_date})"
    )
    return filtered


def get_updated_assignments(username: str, password: str, date: int, max_retries: int = 3, backoff_seconds: int = 5):
    url = f"https://data.edulastic.com/assignment-list?date={date}"

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(url, auth=(username, password), timeout=35)
            print(f"Date: {datetime.utcfromtimestamp(date).strftime('%Y-%m-%d')} | Status: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                print(data)
                if data:
                    logging.info(f"Assignments retrieved for {date}")
                    return pd.DataFrame(data)
                return None

            logging.warning(
                f"Assignment-list request failed for {date} with status {response.status_code} "
                f"(attempt {attempt}/{max_retries})"
            )
        except (requests.RequestException, ValueError) as e:
            logging.warning(
                f"Assignment-list request failed for {date}: {e} "
                f"(attempt {attempt}/{max_retries})"
            )

        if attempt < max_retries:
            time.sleep(backoff_seconds * attempt)

    raise RuntimeError(
        f"Assignment-list API failed for {datetime.utcfromtimestamp(date).strftime('%Y-%m-%d')} "
        f"after {max_retries} attempts. Full refresh is incomplete; stopping before upload."
    )

    return None


def collect_daily_assignments(username: str, password: str, start_date: datetime, delay_seconds: int = 1):
    start_date, end_date = resolve_date_range(start_date)
    
    all_results = []

    current_date = start_date
    while current_date <= end_date:
        epoch_timestamp = int(time.mktime(current_date.timetuple()))
        df = get_updated_assignments(username, password, epoch_timestamp)

        if df is not None and not df.empty:
            df['query_date'] = current_date.strftime("%Y-%m-%d")
            all_results.append(df)

        # Wait before the next API call
        print(f"Sleeping {delay_seconds} seconds before next call...")
        time.sleep(delay_seconds)

        current_date += timedelta(days=1)

    if all_results:
        final_df = pd.concat(all_results, ignore_index=True)
        final_df.columns = ['assignment_id', 'query_date']
        logging.info(f'Here is the number of assignments updated since the beginning of the year {len(final_df)}')
        final_df = final_df.drop_duplicates(subset=['assignment_id'])
        logging.info(f'After dropping duplicates going to iterate through {len(final_df)}')

        # final_df.to_csv("assignments_aug1_to_oct21.csv", index=False)
        # print("✅ Saved results to assignments_aug1_to_oct21.csv")
        return final_df
    else:
        print("⚠️ No data returned for any date.")
        return None
