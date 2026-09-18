import io
import requests
import pandas as pd

PHS_API = (
    "https://www.opendata.nhs.scot/api/3/action/"
    "package_show?id=monthly-accident-and-emergency-activity-and-waiting-times"
)

OUTPUT_FILE = "ae_waiting_times.csv"


def get_latest_phs_csv():
    response = requests.get(PHS_API, timeout=60)
    response.raise_for_status()

    resources = response.json()["result"]["resources"]

    csv_resources = [
        r for r in resources
        if r.get("format", "").upper() == "CSV"
        and "monthly_ae_activity" in r.get("url", "").lower()
    ]

    if not csv_resources:
        raise RuntimeError(
            "Could not find the PHS monthly A&E CSV."
        )

    # Pick the resource with the latest YYYYMM in its filename.
    def resource_month(resource):
        url = resource.get("url", "")
        filename = url.rsplit("/", 1)[-1]
        digits = "".join(c for c in filename if c.isdigit())
        return digits[-6:] if len(digits) >= 6 else "000000"

    return max(csv_resources, key=resource_month)["url"]


def download_phs_data(url):
    print("Downloading PHS data:")
    print(url)

    response = requests.get(url, timeout=120)
    response.raise_for_status()

    return pd.read_csv(
        io.BytesIO(response.content),
        dtype={"Month": str}
    )


def main():
    source_url = get_latest_phs_csv()
    df = download_phs_data(source_url)

    required_columns = [
        "Month",
        "Country",
        "TreatmentLocation",
        "AttendanceCategory",
        "NumberOfAttendancesAll",
        "NumberWithin4HoursAll",
    ]

    missing = [
        column for column in required_columns
        if column not in df.columns
    ]

    if missing:
        raise RuntimeError(
            f"PHS dataset structure has changed. "
            f"Missing columns: {missing}"
        )

    # Scotland's official geography code.
    df = df[
        df["Country"].astype(str).str.strip()
        == "S92000003"
    ].copy()

    # Use one row per treatment location.
    # The PHS file contains an 'All' attendance-category row
    # for each treatment location.
    df = df[
        df["AttendanceCategory"].astype(str).str.strip()
        == "All"
    ].copy()

    if df.empty:
        raise RuntimeError(
            "No Scotland / All rows were found."
        )

    # Month is supplied by PHS as YYYYMM, e.g. 202607.
    df["Month"] = (
        df["Month"]
        .astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .str.zfill(6)
    )

    if not df["Month"].str.fullmatch(r"\d{6}").all():
        raise RuntimeError(
            "Unexpected values found in the PHS Month column."
        )

    df["MonthDate"] = pd.to_datetime(
        df["Month"],
        format="%Y%m",
        errors="coerce"
    )

    if df["MonthDate"].isna().any():
        raise RuntimeError(
            "One or more PHS months could not be converted to dates."
        )

    # Convert the two count fields to numbers.
    for column in [
        "NumberOfAttendancesAll",
        "NumberWithin4HoursAll",
    ]:
        df[column] = pd.to_numeric(
            df[column],
            errors="coerce"
        )

    if df[
        [
            "NumberOfAttendancesAll",
            "NumberWithin4HoursAll",
        ]
    ].isna().any().any():
        raise RuntimeError(
            "Unexpected non-numeric values found in PHS counts."
        )

    # Calculate the Scotland-wide percentage from the counts.
    monthly = (
        df.groupby("MonthDate", as_index=False)
        .agg(
            NumberOfAttendancesAll=(
                "NumberOfAttendancesAll",
                "sum"
            ),
            NumberWithin4HoursAll=(
                "NumberWithin4HoursAll",
                "sum"
            ),
        )
    )

    monthly["PercentageWithin4HoursAll"] = (
        monthly["NumberWithin4HoursAll"]
        / monthly["NumberOfAttendancesAll"]
        * 100
    ).round(1)

    # Convert each YYYYMM month to its month-end date.
    monthly["MonthEndingDate"] = (
        monthly["MonthDate"]
        + pd.offsets.MonthEnd(0)
    )

    output = monthly[
        [
            "MonthEndingDate",
            "PercentageWithin4HoursAll",
        ]
    ].copy()

    output = output.sort_values("MonthEndingDate")

    # -----------------------------
    # SAFETY CHECKS
    # -----------------------------

    if output.empty:
        raise RuntimeError(
            "Output is empty. CSV will not be overwritten."
        )

    if output["MonthEndingDate"].duplicated().any():
        raise RuntimeError(
            "Duplicate months detected. CSV will not be overwritten."
        )

    if (
        output["PercentageWithin4HoursAll"]
        .between(0, 100)
        .all()
        is False
    ):
        raise RuntimeError(
            "Percentage outside 0-100 detected."
        )

    if output["MonthEndingDate"].dt.year.min() < 2007:
        raise RuntimeError(
            "Unexpected date detected."
        )

    # Historical sanity check.
    # July 2007 should be approximately 96%.
    july_2007 = output[
        output["MonthEndingDate"]
        == pd.Timestamp("2007-07-31")
    ]

    if july_2007.empty:
        raise RuntimeError(
            "July 2007 validation month is missing."
        )

    july_value = july_2007[
        "PercentageWithin4HoursAll"
    ].iloc[0]

    if not 94 <= july_value <= 98:
        raise RuntimeError(
            f"Historical validation failed: "
            f"July 2007 = {july_value}%"
        )

    # Only write the CSV AFTER all checks have passed.
    output["MonthEndingDate"] = (
        output["MonthEndingDate"]
        .dt.strftime("%Y-%m-%d")
    )

    output.to_csv(
        OUTPUT_FILE,
        index=False
    )

    print("\nValidation passed.")
    print(f"Created {OUTPUT_FILE}")
    print(f"Rows: {len(output)}")

    print("\nLatest five months:")
    print(output.tail().to_string(index=False))


if __name__ == "__main__":
    main()
