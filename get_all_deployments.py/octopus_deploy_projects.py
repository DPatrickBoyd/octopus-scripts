import os
import requests
import json
import pytz
from datetime import datetime
from collections import defaultdict
import concurrent.futures
import warnings

# Suppress warnings about requests dependencies
warnings.filterwarnings("ignore", category=requests.packages.urllib3.exceptions.InsecureRequestWarning)

# Octopus Deploy API credentials and base URL
OCTOPUS_API_KEY = os.getenv('OCTOPUS_API_KEY')
OCTOPUS_BASE_URL = "https://octopus.example.com"
SPACE_ID = "Spaces-1"

# Set headers with API key for Octopus
headers = {
    'X-Octopus-ApiKey': OCTOPUS_API_KEY,
    'Content-Type': 'application/json'
}

DEBUG_LOG_FILE = "debug_log.txt"

def convert_to_pdt(utc_time):
    utc_zone = pytz.utc
    pdt_zone = pytz.timezone('America/Los_Angeles')
    utc_datetime = datetime.strptime(utc_time, '%Y-%m-%dT%H:%M:%S.%f%z')
    pdt_datetime = utc_datetime.astimezone(pdt_zone)
    return pdt_datetime.strftime('%Y-%m-%d %H:%M:%S PDT')

def log_debug(message):
    timestamp = datetime.now().isoformat()
    with open(DEBUG_LOG_FILE, 'a') as log_file:
        log_file.write(f"{timestamp} - {message}\n")

def log_stdout(message):
    print(message, flush=True)

def make_api_request(endpoint):
    url = f"{OCTOPUS_BASE_URL}/api/{SPACE_ID}/{endpoint}"
    log_debug(f"Making API request to: {url}")
    response = requests.get(url, headers=headers, verify=False)
    if response.status_code == 200:
        log_debug(f"API request successful: {url}")
        return response.json()
    else:
        log_debug(f"API request failed: {response.status_code} - {response.text}")
        return None

def fetch_all_projects():
    log_debug("Fetching all projects")
    projects = make_api_request("projects/all")
    log_debug(f"Fetched {len(projects) if projects else 0} projects")
    return projects or []

def fetch_project_details(project_id):
    log_debug(f"Fetching details for project {project_id}")
    return make_api_request(f"projects/{project_id}")

def fetch_all_project_groups():
    log_debug("Fetching all project groups")
    groups = make_api_request("projectgroups/all")
    log_debug(f"Fetched {len(groups) if groups else 0} project groups")
    return groups or []

def fetch_all_environments():
    log_debug("Fetching all environments")
    environments = make_api_request("environments/all")
    log_debug(f"Fetched {len(environments) if environments else 0} environments")
    return environments or []

def fetch_deployments_with_pagination(project_id, environment_id):
    log_debug(f"Fetching deployments for project {project_id} and environment {environment_id}")
    all_items = []
    skip = 0
    take = 30  # Octopus API default

    while True:
        result = make_api_request(f"deployments?projects={project_id}&environments={environment_id}&skip={skip}&take={take}")
        if not result or not result['Items']:
            break
        
        items_count = len(result['Items'])
        all_items.extend(result['Items'])
        log_debug(f"Fetched {items_count} deployments (total: {len(all_items)})")
        
        if items_count < take:
            break
        
        skip += take

    log_debug(f"Finished fetching deployments. Total: {len(all_items)}")
    return all_items

def process_deployment(project_id, environment_id):
    log_debug(f"Processing deployment for project {project_id} and environment {environment_id}")
    try:
        deployments = fetch_deployments_with_pagination(project_id, environment_id)
        if not deployments:
            log_debug(f"No deployments found for project {project_id} and environment {environment_id}")
            return None

        latest_deployment = deployments[0]
        log_debug(f"Fetching release {latest_deployment['ReleaseId']} for latest deployment")
        release = make_api_request(f"releases/{latest_deployment['ReleaseId']}")
        log_debug(f"Fetching task {latest_deployment['TaskId']} for latest deployment")
        task = make_api_request(f"tasks/{latest_deployment['TaskId']}")
        
        if not release or not task:
            log_debug(f"Failed to fetch release or task for project {project_id} and environment {environment_id}")
            return None
        
        failed = task.get('State', 'Unknown') == 'Failed'
        
        output = {
            "version": release['Version'],
            "release_notes": release.get('ReleaseNotes', None),
            "deployment_date": convert_to_pdt(latest_deployment['Created']),
        }
        
        if failed:
            log_debug(f"Latest deployment failed for project {project_id} and environment {environment_id}. Searching for last successful deployment.")
            output["failed"] = True
            for deployment in deployments[1:]:
                task = make_api_request(f"tasks/{deployment['TaskId']}")
                if task and task.get('State', 'Unknown') == 'Success':
                    success_release = make_api_request(f"releases/{deployment['ReleaseId']}")
                    output["last_successful_version"] = success_release['Version']
                    output["last_successful_date"] = convert_to_pdt(deployment['Created'])
                    log_debug(f"Found last successful deployment for project {project_id} and environment {environment_id}")
                    break
        
        log_debug(f"Finished processing deployment for project {project_id} and environment {environment_id}")
        return environment_id, output
    except Exception as e:
        log_debug(f"Error processing deployment for project {project_id} and environment {environment_id}: {str(e)}")
        return None

def fetch_all_deployment_data():
    log_debug("Starting to fetch all deployment data")
    projects = fetch_all_projects()
    project_groups = fetch_all_project_groups()
    environments = fetch_all_environments()

    log_debug("Grouping projects by project group")
    projects_by_group = defaultdict(list)
    for project in projects:
        projects_by_group[project['ProjectGroupId']].append(project)

    all_results = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        for group in project_groups:
            log_debug(f"Processing project group: {group['Name']}")
            group_projects = projects_by_group[group['Id']]
            
            group_data = {
                "id": group['Id'],
                "name": group['Name'],
                "projects": []
            }
            
            for project in group_projects:
                log_debug(f"Processing project: {project['Name']}")
                log_stdout(f"Processing project: {project['Name']}")
                
                project_details = fetch_project_details(project['Id'])
                git_url = project_details.get('PersistenceSettings', {}).get('Url') if project_details else None
                
                project_data = {
                    "id": project['Id'],
                    "name": project['Name'],
                    "git_url": git_url,
                    "environments": []
                }
                
                futures = {executor.submit(process_deployment, project['Id'], env['Id']): env for env in environments}
                
                env_data = {}
                for future in concurrent.futures.as_completed(futures):
                    env = futures[future]
                    try:
                        result = future.result()
                        if result:
                            env_id, data = result
                            data['name'] = env['Name']
                            env_data[env_id] = data
                            log_debug(f"Added environment data for {env['Name']} to project {project['Name']}")
                    except Exception as exc:
                        log_debug(f"Generated an exception while processing {env['Name']} for project {project['Name']}: {exc}")
                
                # Add all environment data to project
                project_data['environments'] = list(env_data.values())
                
                group_data['projects'].append(project_data)
            
            all_results.append(group_data)
            log_debug(f"Finished processing project group: {group['Name']}")

    log_debug("Finished fetching all deployment data")
    return all_results

if __name__ == "__main__":
    log_debug("Script started")
    log_stdout("Script started")
    all_deployment_data = fetch_all_deployment_data()

    log_debug("Writing data to file")
    log_stdout("Writing data to file")
    with open("all_projects_deployment_data.json", 'w') as output_file:
        json.dump(all_deployment_data, output_file, indent=4)
    
    log_debug("All projects deployment data has been written to all_projects_deployment_data.json")
    log_stdout("All projects deployment data has been written to all_projects_deployment_data.json")
    log_debug("Script completed")
    log_stdout("Script completed")