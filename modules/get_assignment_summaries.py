import requests
import pandas as pd
from pathlib import Path
import base64
import logging
import time

def convert_epoch_columns(df, inplace=True):
    """
    Convert columns containing 'date' or 'timestamp' in their name from epoch to datetime.
    Handles invalid or extreme values safely.
    """
    if not inplace:
        df = df.copy()

    # Include both 'date' and 'timestamp' columns
    date_cols = [c for c in df.columns if 'date' in c.lower() or 'timestamp' in c.lower()]
    for c in date_cols:
        s = pd.to_numeric(df[c], errors='coerce')

        # Drop NaNs before determining the time unit
        valid = s.dropna()
        if valid.empty:
            continue

        # Determine likely unit (milliseconds if median >= 1e12)
        unit = 'ms' if valid.median() >= 1e12 else 's'

        # Clip extreme values that cause overflow in conversion
        min_valid = -2208988800 if unit == 's' else -2208988800000
        max_valid = 1e11 if unit == 's' else 1e14
        s = s.clip(lower=min_valid, upper=max_valid)

        # Convert safely
        try:
            df[c] = pd.to_datetime(s, unit=unit, utc=True, errors='coerce')
        except Exception as e:
            print(f"Skipping {c} due to conversion error: {e}")
            df[c] = pd.NaT

    return df


def build_basic_auth_headers(username: str, password: str):
    """Compute Basic auth header once."""
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}

def get_assignment_summary(
    assignment_id: str,
    headers: dict,
    max_retries: int = 3,
    backoff_seconds: int = 5,
):
    url = f"https://data.edulastic.com/assignment-summary?assignment_id={assignment_id}"

    for attempt in range(1, max_retries + 1):
        try:
            timeout_ = 90
            response = requests.get(url, headers=headers, timeout=timeout_)
            if response.status_code == 200:
                return response
            logging.warning(
                f"Assignment summary request failed for {assignment_id} with status {response.status_code} "
                f"(attempt {attempt}/{max_retries})"
            )
        except requests.RequestException as e:
            logging.warning(
                f"Assignment summary request failed for {assignment_id}: {e} "
                f"(attempt {attempt}/{max_retries})"
            )

        if attempt < max_retries:
            time.sleep(backoff_seconds * attempt)

    raise RuntimeError(f"Assignment summary API failed for {assignment_id} after {max_retries} attempts.")



def get_assignment_summaries(df_assessments: list, username: str, password: str):
    """Loop over DataFrame assessment_ids using one precomputed header."""
    headers = build_basic_auth_headers(username, password)
    holding_list = []
    for idx, aid in enumerate(df_assessments, 1):
        logging.info(f"Fetching assignment summary for {aid} ({idx}/{len(df_assessments)})")
        resp = get_assignment_summary(aid, headers)
        try:
            if resp.text.strip() == "":
                logging.info(f'No data available for {aid}, status code: {resp.status_code if resp else "No Response"}')
            else:
                response_data = pd.DataFrame(resp.json())
                if response_data.empty:
                    logging.info(f'No data available for {aid}, status code: {resp.status_code if resp else "No Response"}')
                else:
                    holding_list.append(response_data)
        except ValueError:
            body_preview = resp.text.strip()[:200]
            logging.info(
                f"No summary data available for {aid}; response was not valid JSON. "
                f"Body preview: {body_preview!r}"
            )

    if not holding_list:
        raise RuntimeError("No assignment summaries were collected. Full refresh is incomplete; stopping before upload.")
    results = pd.concat(holding_list, ignore_index=True)
    results = convert_epoch_columns(results)
    logging.info(f'The number of unique assessments in the results frame is {results["assessment_group_id"].nunique()}')
    return results


def get_test_info(test_id: str, headers: dict):
    """
    Fetch details of a test from Edulastic Test Info API.
    Args:
        test_id (str): The unique identifier of the test.
        headers (dict): Authentication headers (e.g., from build_basic_auth_headers).
    Returns:
        requests.Response: The HTTP response object, or None if request fails.
    """
    url = f"https://data.edulastic.com/test-info?test_id={test_id}"
    try:
        response = requests.get(url, headers=headers, timeout=35)
        response.raise_for_status()
        return response
    except requests.RequestException as e:
        print(f"Request failed for test_id {test_id}: {e}")
        return None


