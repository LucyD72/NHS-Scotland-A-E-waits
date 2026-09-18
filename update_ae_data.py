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

    package = response.json()["result"]
    resources = package["resources"]

    csv_resources = [
        r for r in resources
        if r.get("format", "").upper() == "CSV"
        and "monthly_ae_activity" in r.get("url", "").lower()
    ]

    if not csv_resources:
        raise RuntimeError(
            "Could not find the current PHS monthly A&E CSV."
        )

    return csv_resources[-1]["url"]


def download_phs_data(url):
    print("Downloading:")
    print(url)

    response = requests.get(url, timeout=120)
    response.raise_for_status()

    return pd.read_csv(io.BytesIO(response.content))


def main():
    source_url = get_latest_phs_csv()
    df = download_phs_data(source_url)

    print("\nColumns found:")
    print(df.columns.tolist())

    required_columns = [
        "Month",
        "PercentageWithin4HoursAll"
    ]

    for column in required_columns:
        if column not in df.columns:
            raise RuntimeError(
                f"Expected column '{column}' was not found "
                f"in the PHS dataset."
            )

    # Keep Scotland if the dataset contains a Country column
    if "Country" in df.columns:
        country_values = (
            df["Country"]
            .dropna()
            .astype(str)
            .str.strip()
        )

        if "Scotland" in country_values.unique():
            df = df[
                df["Country"]
                .astype(str)
                .str.strip()
                == "Scotland"
            ]

    # Keep the "All" attendance category if present
    if "AttendanceCategory" in df.columns:
        category_values = (
            df["AttendanceCategory"]
            .dropna()
            .astype(str)
            .str.strip()
        )

        if "All" in category_values.unique():
            df = df[
                df["AttendanceCategory"]
                .astype(str)
                .str.strip()
                == "All"
            ]

    # Convert month to a proper date
    df["Month"] = pd.to_datetime(
        df["Month"],
        errors="coerce"
    )

    df = df.dropna(subset=["Month"])

    # Convert percentage to a number
    df["PercentageWithin4HoursAll"] = pd.to_numeric(
        df["PercentageWithin4HoursAll"],
        errors="coerce"
    )

    df = df.dropna(
        subset=["PercentageWithin4HoursAll"]
    )

    # One observation per month
    df = df.drop_duplicates(
        subset=["Month"]
    )

    df = df.sort_values("Month")

    # Create the clean CSV for Datawrapper
    output = df[
        [
            "Month",
            "PercentageWithin4HoursAll"
        ]
    ].copy()

    output = output.rename(
        columns={
            "Month": "MonthEndingDate"
        }
    )

    output["MonthEndingDate"] = (
        output["MonthEndingDate"]
        + pd.offsets.MonthEnd(0)
    ).dt.strftime("%Y-%m-%d")

    output.to_csv(
        OUTPUT_FILE,
        index=False
    )

    print("\nCreated:")
    print(OUTPUT_FILE)

    print("\nLatest data:")
    print(output.tail())

    print(
        f"\nTotal rows: {len(output)}"
    )


if __name__ == "__main__":
    main()
