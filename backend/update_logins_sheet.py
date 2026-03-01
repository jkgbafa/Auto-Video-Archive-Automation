#!/usr/bin/env python3
"""
Update Google Sheet with all platform login credentials.
Writes to a "Logins" tab in the shared tracking spreadsheet.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gspread
from config import GOOGLE_SHEET_URL

CREDS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "google_credentials.json")

# All platform logins extracted from WhatsApp chat + .env
LOGINS = [
    # [Platform, Country, Email, Password, Plan, Status, Notes]
    ["Rumble", "Canada", "ytoffice2023@gmail.com", "SeeMe123!", "Free", "Active", "Phase 1 - all years (1999-2003)"],
    ["BitChute", "UK", "ytoffice2023@gmail.com", "SeeMe123!", "Free", "Active", "Phase 1 - API + curl uploads"],
    ["Dailymotion", "France", "dhmmsocialpublishing@gmail.com", "Fu11Pr00f!", "Free", "Active", "Phase 1 - OAuth API"],
    ["Odysee", "USA", "ytoffice2023@gmail.com", "SeeMe123!SeeMe123!", "Free", "Active", "Phase 1 - all years (1999-2003)"],
    ["pCloud", "Switzerland", "ytoffice2023@gmail.com", "SeeMe26!", "10TB Paid", "Active", "Phase 2 - Darius 2020 source"],
    ["Internxt", "Spain", "ytoffice2023@gmail.com", "SeeMe123!", "5TB Lifetime", "Active", "Phase 2 - Eniola 2021 source"],
    ["Icedrive", "UK", "ytoffice2023@gmail.com", "SeeMe123!", "1TB Lifetime", "Active", "Phase 2 - Eniola 2021 dest (WebDAV)"],
    ["Koofr", "Slovenia", "ytoffice2023@gmail.com", "SeeMe123!", "1TB", "Active", "Phase 2 - Darius 2022 source"],
    ["NicoNico", "Japan", "—", "—", "—", "DROPPED", "No upload API, MFA required, geo-blocked from EU"],
    ["Bilibili", "China", "ytoffice2023@gmail.com", "SeeMe123!", "Free", "Active", "Phase 2 - Darius 2020 dest, verified"],
    ["YouTube", "USA", "ytoffice2023@gmail.com", "SeeMe123!", "Free", "Active", "Source platform (archiving FROM)"],
    ["Telegram Bot", "—", "Bot Token: 8316483220:AAF...", "Chat ID: 816709817", "—", "Active", "Notifications"],
    ["Google Sheets", "—", "Service Account", "google_credentials.json", "—", "Active", "Progress tracking"],
    ["PayPal", "—", "econference190@gmail.com", "Cambridge@1", "—", "Active", "Payments for platform subscriptions"],
    ["Claude AI", "—", "dhmm2023@gmail.com", "Socialmediavirtualoffice26", "Max Plan", "Active", "Automation development"],
]

HEADERS = ["Platform", "Country", "Email / Username", "Password / Key", "Plan", "Status", "Notes"]


def update_logins():
    """Write all logins to the 'Logins' tab."""
    if not GOOGLE_SHEET_URL:
        print("No GOOGLE_SHEET_URL configured")
        return False

    try:
        gc = gspread.service_account(filename=CREDS_PATH)
        sh = gc.open_by_url(GOOGLE_SHEET_URL)

        # Get or create the Logins worksheet
        try:
            ws = sh.worksheet("Logins")
            ws.clear()
        except gspread.exceptions.WorksheetNotFound:
            ws = sh.add_worksheet(title="Logins", rows=30, cols=10)

        # Write headers
        ws.append_row(HEADERS)

        # Write all logins
        for login in LOGINS:
            ws.append_row(login)

        # Format header row (bold)
        ws.format('A1:G1', {'textFormat': {'bold': True}})

        print(f"Updated Logins sheet with {len(LOGINS)} entries")
        return True

    except Exception as e:
        print(f"Failed to update Logins sheet: {e}")
        return False


if __name__ == "__main__":
    update_logins()
