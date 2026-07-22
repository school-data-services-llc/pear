import re
import pandas as pd
import logging

keywords = {
    "algebra ii": "Algebra II",
    "algebra i": "Algebra I",
    "geometry": "Geometry",
    "science": "Science",
    "math": "Math"
}

# Assessment ID overrides for curriculum and unit mapping
# These override the automatic categorization when assignment names are ambiguous
assessment_overrides = {
    "68b22e718bbeb32951baaddf": {"curriculum": "Chemistry", "unit": "Interim 1"},  # 10th Grade Science Interim #1
    "690bc60f9f7d11ef8ccd4ace": {"curriculum": "Algebra II", "unit": "Unit 3"},  # Grade 11 Math Unit 3 Assessment*
    "6917b5dd477a07bb7337dfe8": {"curriculum": "Geometry", "unit": "Unit 3"},  # Grade 10 Math Unit 3 Assessment
}

def categorize_curriculum(name: str, assessment_id: str = None) -> str:
    # Check assessment_id override first
    if assessment_id and assessment_id in assessment_overrides:
        return assessment_overrides[assessment_id]["curriculum"]
    
    name_lower = name.lower()
    for k, v in keywords.items():
        if k in name_lower:
            return v
    return "Other"


# Middle school (6, 7, 8): treat "Other" as Math, except 8th grade science interims → Science
MIDDLE_SCHOOL_GRADES = (6, 7, 8)


def apply_middle_school_curriculum(df: pd.DataFrame) -> pd.DataFrame:
    """Where curriculum is Other and grade is 6/7/8, set to Math; except 8th grade science interim → Science."""
    grade_num = pd.to_numeric(df["grade"], errors="coerce")
    other = df["curriculum"] == "Other"
    ms = grade_num.isin([6.0, 7.0, 8.0])
    title_lower = df["title"].astype(str).str.lower()
    # Exception: grade 8 + science + interim (e.g. 8th Grade Science Interim #1) → Science
    eighth_science_interim = (grade_num == 8) & title_lower.str.contains("science", na=False) & title_lower.str.contains("interim", na=False)

    df = df.copy()
    df.loc[other & ms & eighth_science_interim, "curriculum"] = "Science"
    df.loc[other & ms & ~eighth_science_interim, "curriculum"] = "Math"
    return df


def extract_unit(name: str, assessment_id: str = None):
    # Check assessment_id override first
    if assessment_id and assessment_id in assessment_overrides:
        return assessment_overrides[assessment_id]["unit"]
    
    name_lower = name.lower()
    # Try to match "unit <number>"
    match_unit = re.search(r'unit\s*(\d+)', name_lower)
    if match_unit:
        return f"Unit {match_unit.group(1)}"
    # Try to match "interim #<number>" or "interim <number>"
    match_interim = re.search(r'interim\s*#?\s*(\d+)', name_lower)
    if match_interim:
        return f"Interim {match_interim.group(1)}"
    return None  # or "No Unit"

# Function to assign performance level
def get_performance_band(score):
    if score >= 90:
        return 4, "Exceeds Expectations"
    elif score >= 70:
        return 3, "Meets Expectations"
    elif score >= 60:
        return 2, "Approaching Expectations"
    else:
        return 1, "Does Not Meet Expectations"


def drop_null_local_student_ids_or_grade(df: pd.DataFrame, log_prefix: str = "view") -> pd.DataFrame:
    """Drop rows with null/invalid local_student_id or null grade (e.g. not in 25-26 roster). Log counts."""
    null_id_mask = (
        df["local_student_id"].isna()
        | (df["local_student_id"].astype(str).str.strip() == "")
        | (df["local_student_id"].astype(str).str.strip().str.lower() == "nan")
    )
    null_grade_mask = df["grade"].isna()
    to_drop = null_id_mask | null_grade_mask
    n_dropped = to_drop.sum()
    if n_dropped > 0:
        n_bad_id = null_id_mask.sum()
        n_null_grade = null_grade_mask.sum()
        logging.info(
            f"[{log_prefix}] Dropped {n_dropped} rows: {n_bad_id} with null/invalid local_student_id, "
            f"{n_null_grade} with null grade (no match in 25-26 roster, e.g. ID from pq_StudentDemos but not in student_to_teacher)."
        )
        return df[~to_drop].copy()
    return df


def make_view_summaries(df, year, client):

    df['data_source'] = 'pear'
    df['year'] = year
    df['test_type'] = 'assessment'
    df['standard_code'] = 'percent'
    df['curriculum'] = df.apply(lambda row: categorize_curriculum(row['assignment_name'], row['assessment_id']), axis=1)
    df['unit'] = df.apply(lambda row: extract_unit(row['assignment_name'], row['assessment_id']), axis=1)

    # Apply the function
    df[['performance_band_level', 'performance_band_label']] = df['percent_score'].apply(
        lambda x: pd.Series(get_performance_band(x))
    )

    # Optional combined "Proficiency" column
    df['proficiency'] = df['performance_band_level'].astype(str) + " " + df['performance_band_label']

    df.rename(columns={'submitted_date': 'date_taken',
                    'studentsisid': 'local_student_id',
                    'assignment_name': 'title',
                    'percent_score': 'score'}, inplace=True)

    # Log why grade might be null: no match for local_student_id (see swap_student_ids logs for raw vs unmapped)
    null_local = df['local_student_id'].isna().sum()
    nan_str = (df['local_student_id'].astype(str).str.strip() == 'nan').sum()
    logging.info(f"[Summaries view] Rows with null local_student_id before grade merge: {null_local} (incl. {nan_str} 'nan' string). These get null grade. See '[studentsisid]' logs for breakdown: missing in raw PEAR vs not found in PowerSchool.")

    query = f"""
    SELECT student_number as local_student_id,
    grade_level as grade
    FROM `icef-437920.views.student_to_teacher`
    WHERE year = '{year}'
    """
    temp = client.query(query).to_dataframe()

    temp['local_student_id'] = temp['local_student_id'].astype(str)
    df['local_student_id'] = df['local_student_id'].astype(str)

    df = pd.merge(df, temp, on='local_student_id', how='left')
    df = drop_null_local_student_ids_or_grade(df, log_prefix="Summaries view") #necessary to drop students that are not in most recent student_to_teacher table
    df = apply_middle_school_curriculum(df)

    df = df[['data_source', 'assessment_id', 'year', 'date_taken', 'grade', 'local_student_id', 'test_type', 'curriculum', 'unit', 'title', 'standard_code', 'score', 'performance_band_level', 'performance_band_label', 'proficiency']]

    return(df)


def make_view_assignments(df, year, client):
    df['data_source'] = 'pear'
    df['year'] = year
    df['test_type'] = 'assessment'
    df['curriculum'] = df.apply(lambda row: categorize_curriculum(row['assignment_name'], row['assessment_id']), axis=1)
    df['unit'] = df.apply(lambda row: extract_unit(row['assignment_name'], row['assessment_id']), axis=1)

        # Apply the function
    df[['performance_band_level', 'performance_band_label']] = df['percent_score'].apply(
        lambda x: pd.Series(get_performance_band(x))
    )

    # Optional combined "Proficiency" column
    df['proficiency'] = df['performance_band_level'].astype(str) + " " + df['performance_band_label']

    df = df.drop(columns=['score']) #drop old score column that is not a percent. Before changing percent_score name 

    df.rename(columns={'timestamp': 'date_taken',
                'student_sis_id': 'local_student_id',
                'assignment_name': 'title',
                'standard_notation': 'standard_code',
                'percent_score': 'score'}, inplace=True)
    
    query = f"""
    SELECT student_number as local_student_id,
    grade_level as grade
    FROM `icef-437920.views.student_to_teacher`
    WHERE year = '{year}'
    """
    temp = client.query(query).to_dataframe()

    temp['local_student_id'] = temp['local_student_id'].astype(str)
    df['local_student_id'] = df['local_student_id'].astype(str)
    
    # Log merge statistics
    logging.info(f"Before merge: {len(df)} rows, {df['local_student_id'].nunique()} unique local_student_ids")
    logging.info(f"Grade lookup table: {len(temp)} rows, {temp['local_student_id'].nunique()} unique local_student_ids")
    
    # Log why grade might be null: no match for local_student_id (see swap_student_ids logs for raw vs unmapped)
    null_ids_before = df['local_student_id'].isna().sum()
    nan_str = (df['local_student_id'].astype(str).str.strip() == 'nan').sum()
    if null_ids_before > 0:
        logging.warning(f"[Assignments view] Rows with null local_student_id before grade merge: {null_ids_before} (incl. {nan_str} 'nan' string). These get null grade. See '[student_sis_id]' logs for breakdown: missing in raw PEAR vs not found in PowerSchool.")

    df = pd.merge(df, temp, on='local_student_id', how='left')
    df = drop_null_local_student_ids_or_grade(df, log_prefix="Assignments view") #necessary to drop students that are not in most recent student_to_teacher table
    df = apply_middle_school_curriculum(df)

    # Log merge results
    matched_count = df['grade'].notna().sum()
    unmatched_count = df['grade'].isna().sum()
    logging.info(f"After merge: {matched_count} rows with grade, {unmatched_count} rows without grade (null)")

    df = df[['data_source', 'assessment_id', 'year', 'date_taken', 'grade', 'local_student_id', 'test_type', 'curriculum', 'unit', 'title', 'standard_code', 'score', 'performance_band_level', 'performance_band_label', 'proficiency']]
    return(df)