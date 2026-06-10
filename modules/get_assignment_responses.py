import requests
from .get_assignment_summaries import build_basic_auth_headers, convert_epoch_columns
import pandas as pd
import time
import logging

def get_assignment_responses(
    assignment_id: str,
    headers: dict,
    date: int = None,
    max_retries: int = 3,
    backoff_seconds: int = 5,
):
    """
    Fetch student responses for each question for a specific assignment.
    """
    base_url = "https://data.edulastic.com/assignment-responses"
    params = {"assignment_id": assignment_id}
    if date is not None:
        params["date"] = date

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(base_url, headers=headers, params=params, timeout=35)
            if response.status_code == 200:
                return response
            logging.warning(
                f"Assignment responses request failed for {assignment_id} with status {response.status_code} "
                f"(attempt {attempt}/{max_retries})"
            )
        except requests.RequestException as e:
            logging.warning(
                f"Assignment responses request failed for {assignment_id}: {e} "
                f"(attempt {attempt}/{max_retries})"
            )

        if attempt < max_retries:
            time.sleep(backoff_seconds * attempt)

    raise RuntimeError(f"Assignment responses API failed for {assignment_id} after {max_retries} attempts.")


def get_assignment_responses_call(username: str, password: str, a_id_list: list, delay_seconds: int = 2):
    headers = build_basic_auth_headers(username, password)
    all_dataframes = []

    for idx, assignment_id in enumerate(a_id_list, 1):
        response = get_assignment_responses(assignment_id, headers)
        try:
            if response.text.strip() == "":
                print(f"ℹ️ No student responses available for {assignment_id} ({idx}/{len(a_id_list)})")
            else:
                data = response.json()
                if isinstance(data, dict):
                    # some APIs return nested dicts — handle that
                    df = pd.json_normalize(data)
                else:
                    df = pd.DataFrame(data)
                if df.empty:
                    print(f"ℹ️ No student responses available for {assignment_id} ({idx}/{len(a_id_list)})")
                else:
                    df["assignment_id"] = assignment_id
                    all_dataframes.append(df)
                    print(f"✅ Collected data for {assignment_id} ({idx}/{len(a_id_list)})")
        except ValueError:
            body_preview = response.text.strip()[:200]
            logging.info(
                f"No student responses available for {assignment_id}; "
                f"response was not valid JSON. Body preview: {body_preview!r}"
            )
            print(f"ℹ️ No student responses available for {assignment_id} ({idx}/{len(a_id_list)})")

        time.sleep(delay_seconds)

    if all_dataframes:
        final_df = pd.concat(all_dataframes, ignore_index=True)
        final_df = convert_epoch_columns(final_df)
        # final_df.to_csv("all_assignment_responses.csv", index=False)
        # print("✅ Saved all responses to all_assignment_responses.csv")
        return final_df
    else:
        print("⚠️ No data collected.")
        return None

