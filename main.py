import os
os.environ["GOOGLE_APPLICATION_CREDENTIALS"]="/home/sam/icef-437920.json"
from modules.access_secrets import *
from modules.normalizing import *
from modules.epoch_compliance import *
from modules.get_assignment_responses import *
from modules.transforming_assignment_responses import *
from modules.get_assignment_summaries import *
from modules.transforming_assignment_summaries import *
from modules.create_main_views import *
from modules.gcs_upload_guards import validate_upload_row_count
import logging
import sys
import time
from gcp_utils_sds import append_assessment_titles, buckets
import pandas as pd
from google.cloud import bigquery
pd.set_option('display.max_columns', None)  # Show all columns when printing DataFrames

logging.basicConfig(
    level=logging.INFO,  # Adjust as needed (e.g., DEBUG, WARNING)
    format="%(asctime)s - %(message)s",  # Log format
    datefmt="%d-%b-%y %H:%M:%S",  # Date format
    handlers=[
        logging.StreamHandler(sys.stdout)  # Direct logs to stdout
    ],
    force=True  # Ensures existing handlers are replaced
)


def main(year):
    client = bigquery.Client(project='icef-437920')
    username = "icefdata@icefps.org"
    password = access_secret_version(project_id='icef-437920', secret_id='pear_password')
    df = collect_daily_assignments(username, password, delay_seconds=1)    #To get all asssignments going back to beginning of August 
    logging.info(f'Here is the number of assignments since the beginning of the year {len(df)}')

    assignment_id_list = df.assignment_id.to_list() + [
    '68c0991821a3b97a63808f7a',
    '689bb78d965cf7826eb6444d',
    '68e5793913c3d26b49c17750',
    '6012eac831d9b500078e5b9e',
    '60411f8af61767000862a9ab',
    '606c6da4d2589a000868a7ff',
    '65eb39c8b54b1d4f2d92a497',
    '67f66e1371cc367444d72a4a',
    '697a7cb021a5d4e7a3020717'
    ] #assignments that are missing from Pears assignment-list endpoint because they do not have standards attached.
    
    logging.info(f'Total assignments to process (including {len(assignment_id_list) - len(df)} hardcoded IDs): {len(assignment_id_list)}')

    df_assignment_responses_raw = get_assignment_responses_call(username, password, assignment_id_list)
    if df_assignment_responses_raw is not None and not df_assignment_responses_raw.empty:
        append_assessment_titles(
            frame=df_assignment_responses_raw,
            project_id="icef-437920",
            data_source="pear",
            column_map={"title": "assignment_name"},
            year=year,
            batch_id=f"pear_assignment_responses_{int(time.time())}",
        )
    df_ar_transformed = transform_assignment_responses(df_assignment_responses_raw, client)
    assignments_view = make_view_assignments(df_ar_transformed, year, client)

    df_assignment_summaries_raw = get_assignment_summaries(assignment_id_list, username, password)
    if df_assignment_summaries_raw is not None and not df_assignment_summaries_raw.empty:
        append_assessment_titles(
            frame=df_assignment_summaries_raw,
            project_id="icef-437920",
            data_source="pear",
            column_map={"title": "assignment_name"},
            year=year,
            batch_id=f"pear_assignment_summaries_{int(time.time())}",
        )
    df_assignment_summaries_transformed = transform_assignment_summaries(df_assignment_summaries_raw, client)
    summaries_view = make_view_summaries(df_assignment_summaries_transformed, year, client)

    uploads = [
        (df_assignment_responses_raw, "pear_assignment_responses_raw.csv"),
        (df_ar_transformed, "pear_assignment_responses.csv"),
        (assignments_view, "pear_assignment_responses_view.csv"),
        (df_assignment_summaries_transformed, "pear_assignment_summaries.csv"),
        (df_assignment_summaries_raw, "pear_assignment_summaries_raw.csv"),
        (summaries_view, "pear_assignment_summaries_view.csv"),
    ]

    for frame, frame_name in uploads:
        validate_upload_row_count(frame, frame_name, dag_name='pear_processing_dag', client=client)

    for frame, frame_name in uploads:
        buckets.send_to_gcs(
            'pearbucket-icefschools-1',
            "",
            frame,
            frame_name,
            project_id='icef-437920',
            dag_name='pear_processing_dag',
        )

main(year='25-26')