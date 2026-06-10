import os

from google.cloud import bigquery


MIN_UPLOAD_ROW_RATIO = 0.95


def get_previous_upload_row_count(client, table_name, dag_name):
    query = """
    SELECT current_rows_added
    FROM `icef-437920.logging.data_pipeline_audit`
    WHERE table_name = @table_name
      AND dag_name = @dag_name
    ORDER BY run_date DESC
    LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("table_name", "STRING", table_name),
            bigquery.ScalarQueryParameter("dag_name", "STRING", dag_name),
        ]
    )
    result = client.query(query, job_config=job_config).result()
    row = next(result, None)
    return row.current_rows_added if row else None


def validate_upload_row_count(frame, frame_name, dag_name, client):
    table_name = os.path.splitext(frame_name)[0]
    current_rows = len(frame)
    previous_rows = get_previous_upload_row_count(client, table_name, dag_name)

    if previous_rows is not None and current_rows < previous_rows * MIN_UPLOAD_ROW_RATIO:
        raise RuntimeError(
            f"Refusing to upload {frame_name}: current row count {current_rows} is below "
            f"{MIN_UPLOAD_ROW_RATIO:.0%} of previous row count {previous_rows}. "
            "Full refresh may be incomplete."
        )
