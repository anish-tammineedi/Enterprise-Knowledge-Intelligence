import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs" / "dataset.json"
RAW_DIR = ROOT / "data" / "raw" / "sec_filings"
SOURCES_PATH = ROOT / "data" / "metadata" / "sources.json"

SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"
REQUEST_TIMEOUT = 30
REQUEST_INTERVAL = 0.25

def load_json(path):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    with temporary_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)
        file.write("\n")
    temporary_path.replace(path)


class SecClient:
    def __init__(self, session=None, interval=REQUEST_INTERVAL):
        self.session = session or requests.Session()
        user_agent = os.environ.get("SEC_USER_AGENT", "").strip()
        if not user_agent:
            raise ValueError("SEC_USER_AGENT must be set before making SEC requests")
        self.session.headers.update({"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"})
        self.interval = interval
        self.last_request_at = None

    def get(self, url, timeout=REQUEST_TIMEOUT):
        if self.last_request_at is not None:
            elapsed = time.monotonic() - self.last_request_at
            if elapsed < self.interval:
                time.sleep(self.interval - elapsed)
        try:
            response = self.session.get(url, timeout=timeout)
        finally:
            self.last_request_at = time.monotonic()
        response.raise_for_status()
        return response


def normalize_cik(cik):
    return str(cik).strip().zfill(10)


def get_submissions(client, cik):
    url = SEC_SUBMISSIONS_URL.format(cik=normalize_cik(cik))
    return client.get(url).json()


def select_filings(submissions, form, limit):
    recent = submissions.get("filings", {}).get("recent", {})
    filings = []

    for index, filing_form in enumerate(recent.get("form", [])):
        if filing_form != form:
            continue
        try:
            filings.append(
                {
                    "form": filing_form,
                    "accession_number": recent["accessionNumber"][index],
                    "filing_date": recent["filingDate"][index],
                    "report_date": recent["reportDate"][index],
                    "primary_document": recent["primaryDocument"][index],
                }
            )
        except (KeyError, IndexError, TypeError):
            continue
        if len(filings) >= limit:
            break

    return filings


def filing_url(company, filing):
    cik = normalize_cik(company["cik"]).lstrip("0") or "0"
    accession = filing["accession_number"].replace("-", "")
    return SEC_ARCHIVES_URL.format(
        cik=cik,
        accession=accession,
        document=filing["primary_document"],
    )


def filing_path(company, filing):
    accession = filing["accession_number"].replace("-", "")
    return RAW_DIR / f"{company['ticker']}_{accession}.html"


def download_filing(client, company, filing, path=None):
    path = path or filing_path(company, filing)
    response = client.get(filing_url(company, filing))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.part")
    temporary_path.write_bytes(response.content)
    temporary_path.replace(path)
    return path


def document_key(document):
    return normalize_cik(document.get("cik", "")), document.get("accession_number")


def build_metadata(company, filing, path, downloaded_at=None):
    return {
        "company": company["name"],
        "ticker": company["ticker"],
        "cik": normalize_cik(company["cik"]),
        "form": filing["form"],
        "filing_date": filing["filing_date"],
        "report_date": filing["report_date"],
        "accession_number": filing["accession_number"],
        "source_url": filing_url(company, filing),
        "downloaded_at": downloaded_at or datetime.now(timezone.utc).isoformat(),
        "local_path": str(path.relative_to(ROOT)),
    }


def validate_config(config):
    companies = config.get("companies")
    limit = config.get("filings_per_company")
    forms = config.get("forms", [])
    if not isinstance(companies, list) or not companies:
        raise ValueError("Configuration must contain a non-empty companies list")
    if not isinstance(limit, int) or limit < 1:
        raise ValueError("filings_per_company must be a positive integer")
    if "10-K" not in forms:
        raise ValueError("Configuration must include 10-K in forms")


def process_company(client, company, limit, sources):
    name = company.get("name", company.get("ticker", "unknown company"))
    print(f"Fetching 10-K filings for {name}...")
    try:
        submissions = get_submissions(client, company["cik"])
        filings = select_filings(submissions, "10-K", limit)
    except (KeyError, TypeError, ValueError, requests.RequestException, json.JSONDecodeError) as error:
        print(f"Failed to fetch filings for {name}: {error}")
        return 0, 0, 1

    if not filings:
        print(f"No 10-K filings found for {name}")
        return 0, 0, 0

    documents = sources.setdefault("documents", [])
    known_documents = {document_key(document) for document in documents}
    downloaded = 0
    skipped = 0
    failed = 0

    for filing in filings:
        key = normalize_cik(company["cik"]), filing["accession_number"]
        path = filing_path(company, filing)
        previous = next((document for document in documents if document_key(document) == key), None)
        if key in known_documents and path.exists():
            print(f"Skipped existing filing {filing['accession_number']} ({path.name})")
            skipped += 1
            continue

        try:
            if path.exists():
                timestamp = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
                print(f"Found existing filing {path.name}; recording metadata")
            else:
                download_filing(client, company, filing, path)
                timestamp = datetime.now(timezone.utc).isoformat()
                print(f"Downloaded {path.name}")
                downloaded += 1
            metadata = build_metadata(company, filing, path,
                                      previous.get("downloaded_at") if previous else timestamp)
            if previous is None:
                documents.append(metadata)
                known_documents.add(key)
                save_json(SOURCES_PATH, sources)
            elif previous != metadata:
                documents[documents.index(previous)] = metadata
                save_json(SOURCES_PATH, sources)
        except (OSError, ValueError, requests.RequestException) as error:
            print(f"Failed to download {filing['accession_number']} for {name}: {error}")
            failed += 1

    return downloaded, skipped, failed


def main():
    try:
        config = load_json(CONFIG_PATH)
        validate_config(config)
        sources = load_json(SOURCES_PATH)
        if not isinstance(sources.get("documents"), list):
            raise ValueError("sources.json must contain a documents list")
        RAW_DIR.mkdir(parents=True, exist_ok=True)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"Unable to initialize SEC download: {error}")
        return 1

    try:
        client = SecClient()
    except ValueError as error:
        print(f"Unable to initialize SEC download: {error}")
        return 1
    totals = [0, 0, 0]

    for company in config["companies"]:
        try:
            result = process_company(client, company, config["filings_per_company"], sources)
        except Exception as error:
            name = company.get("name", company.get("ticker", "unknown company"))
            print(f"Failed to process {name}: {error}")
            result = 0, 0, 1
        totals = [total + value for total, value in zip(totals, result)]

    print(f"Finished: {totals[0]} downloaded, {totals[1]} skipped, {totals[2]} failed")
    print(f"Metadata saved to {SOURCES_PATH}")
    return 0 if totals[2] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
