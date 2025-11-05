import requests
import json
import time
import csv
import sys
from datetime import datetime

# ===================== CONFIG =====================
API_KEY = "32ed1a946080b014fbe70fcabddff667092fd8dc"
ORG_ID = 838074
NETWORK_ID = "N_635570497412743556"
BASE_URL = "https://api.meraki.com/api/v1"
CSV_PATH = ""  # optional: e.g., "uplink_status.csv"
# ==================================================

# Meraki API Headers
HEADERS = {
    "X-Cisco-Meraki-API-Key": API_KEY,
    "Accept": "application/json",
    "Content-Type": "application/json"
}

def invoke_meraki(method, uri, data=None):
    """
    Performs an HTTP request to the Meraki API with rate-limit handling (429).
    """
    max_retries = 5
    attempt = 0
    url = BASE_URL + uri

    while True:
        attempt += 1
        try:
            if method.upper() == 'GET':
                response = requests.get(url, headers=HEADERS)
            elif method.upper() == 'POST':
                response = requests.post(url, headers=HEADERS, data=json.dumps(data) if data else None)
            elif method.upper() == 'PUT':
                response = requests.put(url, headers=HEADERS, data=json.dumps(data) if data else None)
            elif method.upper() == 'DELETE':
                response = requests.delete(url, headers=HEADERS)
            else:
                raise ValueError(f"Unsupported method: {method}")

            status_code = response.status_code

            # Handle Rate Limit (429)
            if status_code == 429 and attempt < max_retries:
                retry_after = response.headers.get("Retry-After")
                # Default to 2 seconds if Retry-After header is missing
                sleep_time = int(retry_after) if retry_after else 2
                print(f"Rate limit hit (429). Retrying in {sleep_time} seconds...", file=sys.stderr)
                time.sleep(sleep_time)
                continue

            # Handle success (2xx)
            if 200 <= status_code < 300:
                # Returns JSON content or None if the response is empty (e.g., DELETE)
                return response.json() if response.content else None

            # Handle other errors
            else:
                try:
                    error_content = response.json()
                except json.JSONDecodeError:
                    error_content = response.text
                
                # Raise an exception with detailed error information
                raise requests.exceptions.HTTPError(
                    f"HTTP {status_code} at {url}\n{error_content}"
                )

        except requests.exceptions.RequestException as e:
            # Handle connection errors, timeouts, etc.
            raise Exception(f"An error occurred during the request to {url}: {e}")
            
# ---

def classify_status(raw_status):
    """
    Classifies the raw uplink status. Equivalent to Classifica-Status in PowerShell.
    'active' and 'ready' are considered 'ATIVA' (ACTIVE) or 'PRONTA' (READY).
    """
    raw_status = raw_status.lower() # Ensure case-insensitivity
    if raw_status == 'active':
        return 'ATIVA'
    elif raw_status == 'ready':
        # Using 'PRONTA' as per the PowerShell script's comment/logic
        return 'PRONTA' 
    else:
        # e.g., failed, not connected, connecting, etc.
        return 'FALHA'

# ---

def format_table(data_list):
    """
    Formats the list of dictionaries as a neatly aligned table.
    """
    if not data_list:
        return ""

    # Define the order and headers for the table
    # Matches the PowerShell output: serial, interface, statusInternet, statusRaw, publicIp, ipLocal, lastReportedAt
    columns = [
        ('serial', 'SERIAL'), 
        ('interface', 'INTERFACE'), 
        ('statusInternet', 'STATUSINTERNET'), 
        ('statusRaw', 'STATUSRAW'), 
        ('publicIp', 'PUBLICIP'), 
        ('ipLocal', 'IPLOCAL'), 
        ('lastReportedAt', 'LASTREPORTEDAT')
    ]

    # Calculate max width for each column
    col_widths = {col[0]: len(col[1]) for col in columns}
    for row in data_list:
        for key, header in columns:
            value = str(row.get(key, ''))
            col_widths[key] = max(col_widths[key], len(value))

    # Create the header row
    header_line = "  ".join(header.ljust(col_widths[key]) for key, header in columns)
    
    # Separator line
    separator_line = "  ".join("-" * col_widths[key] for key, header in columns)

    # Create data rows
    data_lines = []
    for row in data_list:
        line = "  ".join(str(row.get(key, '')).ljust(col_widths[key]) for key, header in columns)
        data_lines.append(line)

    return "\n".join([header_line, separator_line] + data_lines)
    
# ---

# --- MAIN SCRIPT EXECUTION ---

# 1. API Call to get Uplink Statuses
try:
    # Meraki API limit: 1000 per page, which is sufficient for most orgs
    uri = f"/organizations/{ORG_ID}/uplinks/statuses?perPage=1000"
    data = invoke_meraki(method='GET', uri=uri)
except Exception as e:
    print(f"Error calling Meraki API: {e}", file=sys.stderr)
    sys.exit(1)

# 2. Process and Filter Data
rows = []
if data:
    for device in data:
        # Filter: Only process devices belonging to the specified networkId
        if device.get('networkId') != NETWORK_ID:
            continue
            
        for uplink in device.get('uplinks', []):
            interface = uplink.get('interface', '').lower()
            # Filter: Only process 'wan1' and 'wan2' interfaces
            if interface in ('wan1', 'wan2'):
                raw_status = uplink.get('status', 'unknown')
                
                # Create the custom object (dictionary in Python)
                rows.append({
                    'organizationId': ORG_ID,
                    'networkId': device.get('networkId'),
                    'serial': device.get('serial'),
                    'model': device.get('model'),
                    # Convert to uppercase as in the PowerShell script
                    'interface': interface.upper(), 
                    'statusRaw': raw_status,
                    # Classification function
                    'statusInternet': classify_status(raw_status), 
                    'publicIp': uplink.get('publicIp'),
                    'ipLocal': uplink.get('ip'),
                    'gateway': uplink.get('gateway'),
                    'lastReportedAt': device.get('lastReportedAt')
                })

# 3. Handle No Results
if not rows:
    print(f"WARNING: Nenhum uplink WAN1/WAN2 encontrado para a rede {NETWORK_ID} na org {ORG_ID}.", file=sys.stderr)
    # The PowerShell script just returns/exits here, so we exit in Python
    sys.exit(0)

# 4. Sort and Format Output
# Sort by interface, then by serial
rows.sort(key=lambda x: (x['interface'], x['serial']))

# Print the formatted table to the console
print(format_table(rows))

# 5. Export to CSV (if CSV_PATH is set)
if CSV_PATH:
    try:
        # Define field names based on the dictionary keys
        fieldnames = list(rows[0].keys())
        
        with open(CSV_PATH, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)
            
        print(f"\nCSV salvo em: {CSV_PATH}")
    except Exception as e:
        print(f"Error saving CSV: {e}", file=sys.stderr)