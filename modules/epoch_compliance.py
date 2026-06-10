import requests
import pandas as pd
from datetime import datetime, timedelta
import time
import logging
from zoneinfo import ZoneInfo


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


def collect_daily_assignments(username: str, password: str, delay_seconds: int = 1):
    tz = ZoneInfo("America/Chicago")
    start_date = datetime(2025, 8, 1, tzinfo=tz)
    end_date = datetime.now(tz)
    
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
